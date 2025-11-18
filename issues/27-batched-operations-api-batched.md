---
number: 27
title: "Batched Operations API (.batched())"
state: open
labels:
---

### 1. Concept

This feature introduces a specific API for high-performance bulk write operations across `DictManager`, `ListManager`, `CollectionManager`, `LogManager`, and `BlobManager`.

While SQLite handles individual writes reasonably well, high-throughput scenarios (like ETL jobs, data migration, high-frequency logging, or initial seeding) perform poorly if every insertion is its own transaction.

We will introduce a `.batched()` method on managers that returns a context manager. Operations performed on the "batch" object are buffered in memory and executed in a single, optimized transaction upon exiting the block.

### 2. Use Cases

* **Bulk Data Ingestion:** Loading 10,000 user profiles into a dictionary from a JSON file.
* **High-Frequency Logging:** Pushing a batch of 500 sensor metrics or request logs without stalling the application.
* **RAG Indexing:** Indexing a corpus of documents where embedding generation happens in batches.
* **Asset Migration:** Bulk uploading a directory of small icon files into a blob store.

### 3. Proposed API

The API uses a context manager pattern (`with ... as batch:`). The `batch` object mirrors the write methods of the parent manager but buffers the data instead of writing immediately.

#### Dictionaries
```python
with db.dict("config").batched() as batch:
    batch["key1"] = "value1"
    batch.set("key2", "value2", ttl_seconds=300)
    # Writes happen atomically here
````

#### Lists

Supports `push` and `prepend` only. Arbitrary indexing/insertion is disabled in batch mode to ensure efficient `item_order` calculation.

```python
with db.list("queue").batched() as batch:
    batch.push("item1")
    batch.push("item2")
    batch.prepend("urgent_item")
    # Calculates all item_orders efficiently and inserts in one go
```

#### Collections

```python
with db.collection("articles").batched() as batch:
    batch.index(doc1)
    batch.index(doc2)
    # Bulk inserts into main storage, FTS, and Vector logs
```

#### Logs

Ensures strict time-ordering to prevent primary key collisions in the database.

```python
with db.log("metrics").batched() as batch:
    for i in range(1000):
        batch.log({"cpu": i})
    # Inserts 1000 records in one transaction
```

#### Blobs

Useful for bulk loading small files.

```python
with db.blobs("icons").batched() as batch:
    batch.put("icon_1.png", data_bytes_1)
    batch.put("icon_2.png", data_bytes_2)
```

### 4\. Implementation Design

Each manager will return a specialized `Batch` subclass (e.g., `DictBatch`, `ListBatch`) that implements `__enter__` and `__exit__`.

#### A. `DictBatch`

  * **State:** `_pending_sets: list[tuple]`.
  * **Logic:**
      * `__setitem__` / `set`: Appends `(key, serialize(value), expiry)` to the list.
      * `__exit__`:
        1.  Acquires the manager's internal lock.
        2.  Opens a transaction.
        3.  Calls `cursor.executemany("INSERT OR REPLACE INTO beaver_dicts ...", _pending_sets)`.

#### B. `ListBatch`

  * **State:** `_pending_push: list`, `_pending_prepend: list`.
  * **Logic:**
      * `push(val)`: Appends to `_pending_push`.
      * `prepend(val)`: Appends to `_pending_prepend`.
      * `__exit__`:
        1.  Acquires lock and transaction.
        2.  Queries `SELECT MIN(item_order), MAX(item_order) FROM beaver_lists ...`.
        3.  Calculates new orders:
              * Prepends: Decrementing from `min_order`.
              * Pushes: Incrementing from `max_order`.
        4.  Constructs a single list of tuples.
        5.  Calls `cursor.executemany(...)`.

#### C. `CollectionBatch`

  * **State:** `_pending_docs: list[Document]`.
  * **Logic:**
      * `index(doc)`: Appends to list.
      * `__exit__`:
        1.  Acquires lock and transaction.
        2.  **Main Table:** Bulk insert all documents into `beaver_collections`.
        3.  **FTS/Fuzzy:** Bulk insert all flattened text fields into `beaver_fts_index` and `beaver_trigrams`.
        4.  **Vectors:**
              * Requires updating `VectorIndex` to support a `index_many(docs, cursor)` method.
              * This method will use `executemany` to insert into `beaver_vector_change_log`.
              * It will then assume the "fast path" update for the in-memory index (iterating over the batch to update the local delta index).

#### D. `LogBatch`

  * **State:** `_pending_logs: list[tuple]`, `_last_ts: float`.
  * **Logic:**
      * `log(data, timestamp=None)`:
          * Calculates `ts = timestamp or time.time()`.
          * **Monotonicity Check:** If `ts <= self._last_ts`, sets `ts = self._last_ts + 1e-6` (microsecond increment).
          * Updates `self._last_ts = ts`.
          * Appends `(ts, serialize(data))` to list.
      * `__exit__`:
        1.  Acquires lock and transaction.
        2.  Calls `cursor.executemany("INSERT INTO beaver_logs ...", _pending_logs)`.

#### E. `BlobBatch`

  * **State:** `_pending_blobs: list[tuple]`.
  * **Logic:**
      * `put(key, data, metadata)`: Appends to list.
      * `__exit__`:
        1.  Acquires lock and transaction.
        2.  Calls `cursor.executemany("INSERT OR REPLACE INTO beaver_blobs ...", _pending_blobs)`.

### 5\. Constraints & Exclusions

  * **Queues Excluded:** `QueueManager` is excluded from this API. Batch *consumption* is handled by `db.queue(...).acquire()`. Batch *production* is rare enough to not warrant a specific API in this pass.
  * **Memory Usage (Blobs):** The batch is held in memory. Users will be warned in documentation not to use `BlobBatch` for large files (e.g., video dumps), as it will cause an OOM error before the write occurs.
  * **List Indexing:** `batch.insert(i, val)` will **not** be supported initially to avoid complex order shifting logic.
  * **Isolation:** Reads inside the `with` block will **not** see the pending writes (standard SQL transaction isolation).
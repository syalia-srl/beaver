---
number: 27
title: "Batched Operations API (.batched())"
state: open
labels:
---

### 1. Concept

This feature introduces a specific API for high-performance bulk write operations across `DictManager`, `ListManager`, and `CollectionManager`.

While SQLite handles individual writes reasonably well, high-throughput scenarios (like ETL jobs, data migration, or initial seeding) perform poorly if every insertion is its own transaction.

We will introduce a `.batched()` method on managers that returns a context manager. Operations performed on the "batch" object are buffered in memory and executed in a single, optimized transaction upon exiting the block.

### 2. Use Cases

* **Bulk Data Ingestion:** Loading 10,000 user profiles into a dictionary from a JSON file.
* **Log Processing:** Pushing a batch of 500 log lines onto a list at once.
* **RAG Indexing:** Indexing a corpus of documents where embedding generation happens in batches.

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

### 5\. Constraints

  * **Memory Usage:** The batch is held in memory. Users should not batch 10GB of data at once (they should chunk it, which `beaver load` already handles).
  * **List Indexing:** `batch.insert(i, val)` will **not** be supported initially to avoid complex order shifting logic.
  * **Isolation:** Reads inside the `with` block will **not** see the pending writes (standard SQL transaction isolation).
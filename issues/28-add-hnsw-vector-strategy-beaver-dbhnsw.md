---
number: 28
title: "Add HNSW Vector Strategy (beaver-db[hnsw])"
state: open
labels:
---

### 1. Concept

This feature introduces a high-performance **Hierarchical Navigable Small World (HNSW)** indexing strategy for `CollectionManager`.

While the default `NumpyVectorIndex` (Linear) is robust and dependency-free, it scales linearly `O(N)`. For datasets >100k vectors, query latency becomes unacceptable.

HNSW provides **`O(log N)` search complexity**, enabling sub-millisecond queries on millions of vectors.

To maintain the "single-file" and "process-safe" guarantees of BeaverDB, we will implement a **Hybrid Snapshot System**:
1.  **Base Index (HNSW):** A serialized HNSW graph stored as a BLOB in the database. It is immutable between compactions.
2.  **Delta Index (Linear):** The existing in-memory buffer for recent writes (from the `beaver_vector_change_log`).

### 2. Dependencies

This will be an **optional** feature.
* **Library:** `hnswlib` (A lightweight, fast C++ implementation with Python bindings).
* **Extra:** `pip install "beaver-db[hnsw]"`

### 3. Implementation Design

We will add a new class `HNSWVectorIndex` in `beaver/vector_strategies/hnsw.py` that implements the async `VectorIndex` protocol (from Issue #24).

#### A. Schema Additions
We need a place to store the heavy serialized graph objects.
```sql
CREATE TABLE IF NOT EXISTS beaver_vector_snapshots (
    collection_name TEXT PRIMARY KEY,
    index_type TEXT NOT NULL, -- 'hnsw', etc.
    blob_data BLOB NOT NULL,
    created_at_log_id INTEGER NOT NULL
);
```

#### B. `HNSWVectorIndex` Class

**Internal State:**

  * `_hnsw_index`: An instance of `hnswlib.Index`.
  * `_delta_vectors`: List of vectors (from the log, not yet in HNSW).
  * `_delta_ids`: List of IDs corresponding to `_delta_vectors`.

**1. Initialization (`__init__` & `_load_base_index`):**

  * Attempts to load the serialized binary from `beaver_vector_snapshots`.
  * If a snapshot exists: `_hnsw_index.load_index(..., allow_replace_deleted=True)`.
  * If no snapshot: Initialize an empty `hnswlib.Index`.

**2. Synchronization (`_sync_deltas`):**

  * Identical logic to `NumpyVectorIndex`.
  * Reads new rows from `beaver_vector_change_log` starting after the snapshot's `created_at_log_id`.
  * Appends them to `_delta_vectors` (Linear buffer).
  * *Note:* We do **not** add them to the HNSW graph in real-time to avoid complex locking/concurrency issues during search. The Delta buffer is small and fast enough.

**3. Search (`search`):**

  * **Async Offloading:** HNSW search releases the GIL but is CPU-bound. To prevent blocking the `AsyncBeaverDB` loop, the actual search call is wrapped in `asyncio.to_thread`.
  * **Step 1 (Base):** Search `_hnsw_index` (returns top K).
  * **Step 2 (Delta):** Linearly search `_delta_vectors` (returns top K).
  * **Step 3 (Merge):** Combine results, filter deleted IDs (tombstones), sort by distance, return top K.

**4. Compaction (`compact`):**
This is the "Heavy Lift" operation.

  * Acquires the compaction lock.
  * **Rebuild:**
    1.  Loads **all** vectors from `beaver_collections` (streaming from `aiosqlite`).
    2.  Initializes a fresh `hnswlib.Index`.
    3.  Bulk indexes all vectors (this is fast in C++).
  * **Serialize:** Calls `index.save_index()` (to a temp path or bytes).
  * **Persist:** Writes the blob to `beaver_vector_snapshots` and clears the logs.

### 4. Multi-Strategy Safety (Snapshot Invalidation)

To prevent data loss when mixing strategies (e.g., a process using Linear strategy compacting the DB, effectively "deleting" the logs that an HNSW process needs), we must enforce **Snapshot Invalidation**.

**Rule:** Any operation that clears the `beaver_vector_change_log` (i.e., `compact()`) MUST delete any existing snapshots in `beaver_vector_snapshots`.

  * **Scenario:** A Linear process runs `compact()`.
  * **Action:** It merges logs to `beaver_collections`, clears the logs, and **deletes the HNSW snapshot**.
  * **Result:** Other HNSW processes will detect the missing snapshot, safely fall back to Linear mode (loading strictly from `beaver_collections`), and maintain data consistency.

### 5. Proposed API & Auto-Detection

The factory method in `BeaverDB` and `CollectionManager` will support an "Auto" mode (`None`).

```python
# In CollectionManager.__init__
def __init__(self, ..., index_strategy: str | None = None):
    if index_strategy is None:
        # Check DB for existing snapshot
        row = await db.execute("SELECT index_type FROM beaver_vector_snapshots WHERE ...")
        index_strategy = row[0] if row else "linear"

    if index_strategy == "hnsw":
        self._vector_index = HNSWVectorIndex(...)
    # ...
```

**Usage:**

```python
# 1. Explicit creation
db.collection("articles", index_strategy="hnsw")

# 2. Auto-detection (Next run)
# Automatically detects the HNSW snapshot and uses HNSW strategy
db.collection("articles")

# 3. Manual Override
# Ignores HNSW snapshot, builds linear index from logs
db.collection("articles", index_strategy="linear")
```

### 6. Roadmap

1.  Add `hnswlib` to `optional-dependencies` in `pyproject.toml`.
2.  Implement `HNSWVectorIndex` class using `async/await` and `asyncio.to_thread`.
3.  Update `CollectionManager` to support `index_strategy=None` (Auto-detection).
4.  Update the `compact()` logic in `NumpyVectorIndex` to implement **Snapshot Invalidation** (delete rows from `beaver_vector_snapshots`).
5.  Add integration tests comparing `linear` vs `hnsw` results and verifying the invalidation fallback.
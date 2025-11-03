---
number: 7
title: "Replace `faiss` with simpler, linear `numpy` vectorial search"
state: closed
labels:
- enhancement
---

### 1. Concept

This feature plan outlines the **complete removal of the external `faiss` dependency**, replacing it with a pure `numpy`-based linear search. This change is motivated by the project's guiding principles of **"Minimal & Optional Dependencies"** and **"Simplicity"**.

`faiss` is a heavy, platform-specific C++ dependency that is a major source of installation friction, which contradicts the simple, "local-first" philosophy of `beaver-db`.

To achieve this, we will replace the `faiss`-based `VectorIndex` with a new `NumpyVectorIndex` class. This new implementation will **retain the existing, robust delta-index architecture** (base index, delta index, tombstones, and compaction) but will use pure `numpy` for all search operations.

This design is a deliberate trade-off that accepts slower search performance in exchange for zero installation friction and a simpler schema:

  * **Fast Writes:** `index()` and `drop()` operations will be fast O(1) database writes, and the writing process will *immediately* update its own memory in O(k) time.
  * **Fast Sync:** Other processes will sync these changes in true O(k) (inserts) and O(d) (deletes) time, not O(N).
  * **Accepted Costs:**
    1.  **O(N) Search:** All searches will become O(N+k) (linear scan) instead of O(log N).
    2.  **O(N) Startup:** The *first* read by any new process will trigger an O(N) rebuild to populate its in-memory index.
    3.  **O(N) Compaction:** The *occasional* `compact()` operation will still be an O(N) task that forces a rebuild across all processes.

### 2. Alignment with Philosophy

  * **Minimal Dependencies:** This is the primary driver. It removes the largest and most complex external dependency, making the `[vector]` extra lightweight and solving the most common installation problem.
  * **Simplicity:** While the delta-index logic remains, the *overall schema* is simplified by removing `faiss`'s complex integer-ID mapping (`_beaver_ann_id_mapping`), allowing us to use user-provided string IDs everywhere.
  * **Multi-Process Safety:** The existing, proven, and robust log-based synchronization model is retained and enhanced, ensuring safe concurrent read/write operations from multiple processes.

### 3. Proposed API

**No API changes are required.** This is a purely internal refactoring. All existing user code will work without modification.

### 4. Implementation Design

The implementation involves replacing `beaver/vectors.py` with a new `NumpyVectorIndex` class and updating the schema in `beaver/core.py`.

#### A. Dependency Changes (`pyproject.toml`)

1.  **Remove** `faiss-cpu` from `[project.optional-dependencies].vector`.
2.  **Add** `numpy` to `[project.optional-dependencies].vector` (as it will no longer be a transitive dependency).

#### B. Schema Changes (`beaver/core.py`)

1.  **Remove** all four `_beaver_ann_...` table creation calls.
2.  **Add** a single, unified log table that uses an auto-incrementing ID for efficient delta-syncing:
    ```sql
    CREATE TABLE IF NOT EXISTS _vector_change_log (
        log_id INTEGER PRIMARY KEY AUTOINCREMENT,
        collection_name TEXT NOT NULL,
        item_id TEXT NOT NULL,
        operation_type INTEGER NOT NULL -- 1 for INSERT, 2 for DELETE
    );
    CREATE INDEX idx_vcl_lookup ON _vector_change_log (collection_name, log_id);
    ```
3.  **Modify** `_create_versions_table()`:
      * The `beaver_collection_versions` table will be simplified to only track compactions: `base_version INTEGER NOT NULL DEFAULT 0`. The `log_id` from the new table will serve as the "delta version."

#### C. New Class: `NumpyVectorIndex` (replaces `beaver/vectors.py`)

This class will manage the in-memory vector state for a single process.

  * **In-Memory State:**

      * `_n_matrix: np.ndarray`, `_n_ids: list[str]` (The base/compacted index)
      * `_k_matrix: np.ndarray`, `_k_ids: list[str]` (The delta/pending index)
      * `_deleted_ids: set[str]` (The tombstones)
      * `_local_base_version: int = -1` (Tracks compactions)
      * `_last_seen_log_id: int = -1` (Tracks deltas)
      * `_lock: threading.Lock`

  * **`_check_and_sync()` (The Core Read Sync):**

      * Reads `db_base_version` from `beaver_collection_versions`.
      * **Compaction Sync (O(N)):**
          * Checks `if self._local_base_version < db_base_version`.
          * If true, acquires lock, **waits with jitter** (`time.sleep(random.uniform(0.0, 1.0))`) to prevent a "thundering herd," re-checks the version, and then runs `_load_base_index()`.
      * **Delta Sync (O(k)):**
          * Queries `_vector_change_log` for all entries WHERE `log_id > self._last_seen_log_id`.
          * Iterates through these `k` new log entries *only*.
          * If `op_type == 1`: Appends new vector to `self._k_matrix` (an O(K+k) copy) and ID to `self._k_ids`.
          * If `op_type == 2`: Adds `item_id` to `self._deleted_ids`.
          * Updates `self._last_seen_log_id` to the max `log_id` seen.

  * **`_load_base_index()` (O(N) Rebuild):**

      * This is the O(N) operation for startup and post-compaction.
      * It rebuilds `self._n_matrix`, `self._k_matrix`, `self._deleted_ids`, and `self._last_seen_log_id` from scratch by reading the *entire* `_vector_change_log` and `beaver_collections` tables.
      * This is the "pay the cost" moment that resets the state for the process.

  * **`_fast_path_insert(vector, id, new_log_id)`:**

      * (Internal method for the writing process)
      * Appends `vector` to `self._k_matrix` (with O(K+k) copy) and `id` to `self._k_ids`.
      * Removes `id` from `self._deleted_ids` (in case it was a re-index).
      * **Crucially, sets `self._last_seen_log_id = new_log_id`** to prevent a self-sync.

  * **`_fast_path_delete(id, new_log_id)`:**

      * (Internal method for the writing process)
      * Adds `id` to `self._deleted_ids`.
      * **Crucially, sets `self._last_seen_log_id = new_log_id`** to prevent a self-sync.

  * **`search()` (O(N+k)):**

      * 1.  Calls `_check_and_sync()` (which is now a true O(k) for delta-only changes).
      * 2.  Performs `numpy` linear scan on `_n_matrix` (O(N)).
      * 3.  Performs `numpy` linear scan on `_k_matrix` (O(k)).
      * 4.  Merges results, filters against `_deleted_ids`, sorts by distance, and returns `top_k`.

#### D. `CollectionManager` Modifications

  * **`index()` (Fast Write):**

      * Will call `self._vector_index.index(document, cursor)` inside its transaction.
      * This new method:
        1.  Logs the insert (`INSERT INTO _vector_change_log ... op_type=1`).
        2.  **Captures the new log ID:** `new_log_id = cursor.lastrowid`.
        3.  **Calls the fast path:** `self._vector_index._fast_path_insert(document.embedding, document.id, new_log_id)`.
      * The existing `if self._needs_compaction(1000): self.compact()` logic remains.

  * **`drop()` (Fast Write):**

      * Will call `self._vector_index.drop(document.id, cursor)` inside its transaction.
      * This new method:
        1.  Logs the delete (`INSERT INTO _vector_change_log ... op_type=2`).
        2.  **Captures the new log ID:** `new_log_id = cursor.lastrowid`.
        3.  **Calls the fast path:** `self._vector_index._fast_path_delete(document.id, new_log_id)`.
      * The compaction check also remains here.

  * **`compact()` (Occasional O(N) Rebuild):**

      * **Compaction Lock:** It will first acquire a "compaction lock" (e.g., using `db.dict("__locks__")`) to ensure only one process compacts at a time.
      * If the lock is acquired, it will:
        1.  Inside a DB transaction: `DELETE FROM beaver_collections` for all IDs in the `_vector_deletions_log`.
        2.  `DELETE FROM _vector_change_log`.
        3.  `UPDATE beaver_collection_versions SET base_version = base_version + 1`.
        4.  This `base_version` change will signal all other processes to run their O(N) `_load_base_index()` (with jitter) on their next `search()`.
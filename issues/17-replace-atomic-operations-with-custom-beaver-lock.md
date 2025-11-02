---
number: 17
title: Replace atomic operations with custom beaver lock
---

### 1. Feature Concept

This feature plan outlines a refactor to replace SQLite-level transactions (`with self._db.connection:`) with BeaverDB's own inter-process locking mechanism (`LockManager`) for all internal "read-modify-write" operations.

The core idea is to introduce a **new, private, internal lock** for each data manager instance. This internal lock will be used to wrap critical sections of code (like `queue.get()` or `list.pop()`) that execute multiple SQL statements and must be atomic across different processes to prevent race conditions.

This new *internal* lock is distinct from the *public* lock introduced in **Issue \#10**. This separation is critical to **prevent deadlocks**. A user can acquire the public lock for a long-running batch operation, and internal methods called within that block (like `.get()`) can safely acquire their own short-lived, private lock without conflicting.

### 2. Details & Justification

#### The Problem with Current Transactions

The current implementation heavily relies on `with self._db.connection:`. In SQLite's WAL mode, this provides ACID guarantees and allows concurrent reads, but it **does not provide multi-process mutual exclusion for read-modify-write sequences.**

**Critical Race Condition Example (`QueueManager.get`):**

The current `_get_item_atomically` method in `beaver/queues.py` is *not* atomic across processes.

1.  **Process A:** Starts `with self._db.connection:`, executes `SELECT rowid... LIMIT 1` and gets `rowid=5`.
2.  **Process B:** Starts `with self._db.connection:` at the same time, executes `SELECT rowid... LIMIT 1` and *also* gets `rowid=5`.
3.  **Process A:** Executes `DELETE ... WHERE rowid = 5` and commits.
4.  **Process B:** Executes `DELETE ... WHERE rowid = 5` and commits.

**Result:** Both processes have received the same task. The atomicity is broken.

#### The Solution: Internal `LockManager`

By wrapping this entire `SELECT`/`DELETE` sequence in an internal `LockManager`, we guarantee that only one process can enter this critical section at a time.

1.  **Process A:** Acquires the internal lock for `queue_tasks`.
2.  **Process B:** Tries to acquire the internal lock for `queue_tasks` and blocks.
3.  **Process A:** Executes `SELECT`, gets `rowid=5`, executes `DELETE`, and releases the lock.
4.  **Process B:** Acquires the internal lock.
5.  **Process B:** Executes `SELECT`. The queue is now empty (or the next item is `rowid=6`), so it waits or gets the next item.

**Result:** The race condition is eliminated.

#### Deadlock Prevention (The User's Warning)

This plan explicitly uses *two* different locks per manager to avoid deadlocks:

1.  **`self._lock` (Public):** The existing lock from **Issue \#10**, named `__lock__list__<name>`. This is for the user to call via `with db.list("my-list") as l:` for batch operations.
2.  **`self._internal_lock` (New & Private):** A new lock, named `__internal_lock__list__<name>`. This is used *only* by internal methods like `.pop()` or `.__delitem__()`.

This design allows a user to do this without deadlocking:

```python
# User acquires the PUBLIC lock
with db.queue("tasks") as q:
    # Method call acquires the PRIVATE lock
    task1 = q.get()
    # Method call acquires the PRIVATE lock again
    task2 = q.get()
# User releases the PUBLIC lock
```

#### Identification of Critical Sections

This internal lock is necessary in any method that reads data from the database and then writes data based on that read in a way that could be invalidated by a concurrent operation.

  * **`beaver/queues.py` (`QueueManager`):**

      * **`_get_item_atomically`:** This is the most critical case. The `SELECT ... LIMIT 1` and subsequent `DELETE ... WHERE rowid = ?` must be wrapped.

  * **`beaver/lists.py` (`ListManager`):**

      * **`__setitem__`:** `SELECT rowid ... OFFSET ?` followed by `UPDATE ... WHERE rowid = ?`.
      * **`__delitem__`:** `SELECT rowid ... OFFSET ?` followed by `DELETE ... WHERE rowid = ?`.
      * **`push`:** `SELECT MAX(item_order)` followed by `INSERT`.
      * **`prepend`:** `SELECT MIN(item_order)` followed by `INSERT`.
      * **`insert`:** The logic to `_get_order_at_index` (SELECT) twice and then `INSERT` based on those values.
      * **`pop`:** `SELECT rowid ... DESC LIMIT 1` followed by `DELETE ... WHERE rowid = ?`.
      * **`deque`:** `SELECT rowid ... ASC LIMIT 1` followed by `DELETE ... WHERE rowid = ?`.

  * **`beaver/dicts.py` (`DictManager`):**

      * **`__getitem__` (TTL check):** The `SELECT` to check `expires_at` and the subsequent `DELETE` if the item is expired is a read-modify-write cycle.
      * **`pop`:** This method calls `__getitem__` and `__delitem__`. If its components are made atomic, `pop` will become atomic by extension.

  * **`beaver/collections.py` (`CollectionManager`):**

      * **`index`:** The entire multi-table insertion block (into `beaver_collections`, `beaver_fts_index`, `_beaver_ann_pending_log`, etc.) must be atomic.
      * **`drop`:** The entire multi-table deletion block.

  * **`beaver/vectors.py` (`VectorIndex`):**

      * **`_get_or_create_int_id`:** The `INSERT OR IGNORE` followed by a `SELECT` is a read-modify-write pattern that needs to be atomic. This is called by `CollectionManager.index`, so it will be protected by the `CollectionManager`'s internal lock.

### 5. High-Level Roadmap

1.  **Add Internal Lock to Managers:**

      * In the `__init__` method of `DictManager`, `ListManager`, `QueueManager`, and `CollectionManager`, add a new *private* `LockManager` instance:
        ```python
        self._internal_lock = LockManager(
            db,
            f"__internal_lock_dict__{name}",
            timeout=5.0,  # A short but safe timeout
            lock_ttl=10.0  # A short TTL to clear crashes
        )
        ```
      * Note: `BlobManager` and `LogManager` methods (`put`, `log`) are single `INSERT OR REPLACE` or `INSERT` queries and are already atomic. They do not require this change.

2.  **Refactor `QueueManager`:**

      * In `beaver/queues.py`, modify `_get_item_atomically` to wrap its entire `with self._db.connection:` block inside `with self._internal_lock:`.

3.  **Refactor `ListManager`:**

      * In `beaver/lists.py`, go through all identified methods (`__setitem__`, `__delitem__`, `push`, `prepend`, `insert`, `pop`, `deque`) and wrap their `with self._db.connection:` blocks inside `with self._internal_lock:`.

4.  **Refactor `DictManager`:**

      * In `beaver/dicts.py`, modify `__getitem__` to wrap the TTL check-and-delete logic inside `with self._internal_lock:`.

5.  **Refactor `CollectionManager`:**

      * In `beaver/collections.py`, wrap the entire `with self._db.connection:` block in both the `index` and `drop` methods inside `with self._internal_lock:`.

6.  **Code Review and Verification:**

      * Manually review all managers to ensure *no* read-modify-write operations exist outside an internal lock.
      * Verify that `with self._db.connection:` is still used *inside* the `with self._internal_lock:` to ensure the SQL operations remain ACID-compliant.
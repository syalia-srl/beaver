---
number: 8
title: "First-class synchronization primitive"
state: closed
labels:
---

### 1. Concept

This feature introduces a **first-class, inter-process synchronization primitive** to `beaver-db`, built directly on SQLite's atomic guarantees. It provides a simple, robust, and *fair* (FIFO) distributed lock that works across multiple, independent Python processes.

The primary motivation is to solve multi-process race conditions, such as the "thundering herd" problem where multiple processes might attempt to run the same expensive maintenance task (like vector compaction) simultaneously.

This `db.lock()` will serve as the **basic, fundamental synchronization strategy** for the library, from which users can build other complex coordination patterns. It is designed to be **deadlock-proof** (via TTL) and **starvation-proof** (via a FIFO queue).

### 2. Use Cases

  * **Singleton Process Coordination:** Guarantee that only one process in a pool runs a specific, expensive task. This is the perfect solution for triggering the `NumpyVectorIndex.compact()` method safely.
  * **Critical Section Protection:** Allow any multi-process application to wrap a block of code in a `with` statement, ensuring that no other process can enter that block at the same time.
  * **Task Scheduling:** Enable a pool of workers to safely elect a "leader" to perform a scheduled task (e.g., "send the 9 AM daily report").

### 3. Proposed API

The API will be an intuitive, Pythonic context manager (`with` statement) provided directly by the `BeaverDB` object.

**New `BeaverDB` Factory Method:**

```python
# In beaver/core.py
from .sync import LockManager

class BeaverDB:
    # ... existing methods ...

    def lock(self,
             name: str,
             timeout: float | None = None,
             lock_ttl: float = 60.0,
             poll_interval: float = 0.1) -> LockManager:
        """
        Returns an inter-process lock manager for a given lock name.

        Args:
            name: The unique name of the lock (e.g., "run_compaction").
            timeout: Max seconds to wait to acquire the lock.
                     If None, it will wait forever.
            lock_ttl: Max seconds the lock can be held. If the process crashes,
                      the lock will auto-expire after this time, preventing
                      a permanent deadlock.
            poll_interval: Seconds to wait between polls. Shorter intervals
                           are more responsive but create more DB I/O.
        """
        return LockManager(self, name, timeout, lock_ttl, poll_interval)
```

**Example Usage:**

```python
db = BeaverDB("my_app.db")

try:
    # This will block until the lock is acquired or it times out
    with db.lock("my_singleton_task", timeout=10, poll_interval=0.5):
        # This code is now a critical section.
        # Only one process in the world can be here at a time.
        run_expensive_daily_report()

except TimeoutError:
    # Failed to get the lock, another process is still working.
    print("Task is already running elsewhere.")
```

### 4. Implementation Design

This feature will be implemented as a new, self-contained `LockManager` and will *not* be built on top of `db.dict()`. It will have its own dedicated table for clean separation of concerns.

**1. New Schema Table (`beaver/core.py`)**
A new table will be added to `_create_all_tables()`:

```python
def _create_locks_table(self):
    """Creates the table for managing inter-process lock waiters."""
    self.connection.execute(
        """
        CREATE TABLE IF NOT EXISTS beaver_lock_waiters (
            lock_name TEXT NOT NULL,
            waiter_id TEXT NOT NULL,
            requested_at REAL NOT NULL,
            expires_at REAL NOT NULL,
            PRIMARY KEY (lock_name, requested_at)
        )
        """
    )
```

* `lock_name` & `requested_at`: The composite `PRIMARY KEY` creates the **fair (FIFO) queue**.
* `waiter_id`: A unique ID for the lock holder (e.g., `"pid:123:ts:456"`) to prevent race conditions during release.
* `expires_at`: A `time.time()` timestamp. This is the critical **deadlock-prevention mechanism**.

**2. New `LockManager` Class (`beaver/sync.py`)**
This new class will contain all the logic for acquiring and releasing the lock.

* **`__enter__` (Acquire Logic):**

1.  Generates a unique `_waiter_id`.
2.  Performs a **single, O(1) `INSERT`** to add itself to the `beaver_lock_waiters` queue with its `waiter_id`, `requested_at = time.time()`, and `expires_at = time.time() + self._lock_ttl`.
3.  Enters a "polite polling" `while True:` loop.
4.  Inside the loop (in a single transaction):
        * **Step 1 (Cleanup):** `DELETE` any waiters in the queue where `expires_at < time.time()`. This clears crashed processes.
        * **Step 2 (Check):** `SELECT waiter_id FROM beaver_lock_waiters WHERE lock_name = ? ORDER BY requested_at ASC LIMIT 1`.
5.  **If `waiter_id == self._waiter_id`:** The process is now at the front of the queue and owns the lock. It `return self`.
6.  **If not:** The process checks for `timeout`, then calls `time.sleep(self._poll_interval)`.

* **`__exit__` (Release Logic):**

    * Performs a **single, atomic, race-condition-free** operation.
    * Executes `DELETE FROM beaver_lock_waiters WHERE lock_name = ? AND waiter_id = ?`.
    * This is an atomic **Compare-and-Delete (CAS)**. It *only* removes its own entry from the queue, which safely allows the next process in the `ORDER BY` to acquire the lock on its next poll.

### 5. Alignment with Philosophy

This feature strongly supports the project's guiding principles.

* **Simplicity and Pythonic API:** The `with db.lock(...):` syntax is the most intuitive and Pythonic way to handle resource locking.
* **Minimal & Optional Dependencies:** This feature adds **zero new dependencies**. It is built entirely on the `sqlite3` standard library.
* **Standard SQLite Compatibility:** The `beaver_lock_waiters` table is a standard, simple table that can be inspected and manually managed by any external SQLite tool, aligning with the "no-magic" data portability principle.
* **Developer Experience:** It solves a hard, real-world concurrency problem (fairness, deadlocks, and races) with a simple, configurable, and robust tool.
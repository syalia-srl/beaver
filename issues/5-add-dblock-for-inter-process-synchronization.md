---
number: 5
title: "Add db.lock() for Inter-Process Synchronization"
state: open
labels:
---

Currently, beaver-db is process-safe for concurrent reads and writes, thanks to SQLite's WAL mode. However, it lacks a high-level, "native" primitive for coordinating logic between multiple independent processes.

This becomes a critical problem in multi-process architectures (e.g., a web server with multiple Gunicorn workers) where a singleton task must be performed. 

A key example is the proposed NumpyVectorIndex.compact() method. If all 10 worker processes hit the compaction threshold simultaneously, they would all try to run the same expensive O(N) rebuild, creating a "thundering herd" that would overload the database.

We need a robust, deadlock-proof, and fair distributed lock to solve this and other coordination problems.

We should add a new, first-class synchronization primitive: db.lock(). This method will return a LockManager object that provides a simple and Pythonic way to ensure only one process (among many) can enter a critical section of code at a time.

The lock must be:

 * Process-Safe: It must work across completely independent Python processes (and eventually, across different machines via the REST API).
 * Deadlock-Proof: It must use a Time-To-Live (TTL) mechanism so that if a process acquires a lock and then crashes, the lock is automatically released after a timeout.
 * Fair (FIFO): It should be starvation-proof. Processes that request the lock should be granted it in the order they asked, not via a random race.
 * Flexible: It should be usable as both a simple with statement and via manual acquire() / release() methods for more complex use cases and for the REST API.

# API

The new feature would be exposed via a new method on the BeaverDB object.

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
                      the lock will auto-expire after this time.
            poll_interval: Seconds to wait between polls. Shorter intervals
                           are more responsive but create more DB I/O.
        """
        return LockManager(self, name, timeout, lock_ttl, poll_interval)
```

### Example 1: Context Manager (Simple Usage)

```python
db = BeaverDB("my_app.db")

try:
    with db.lock("my_singleton_task", timeout=10, poll_interval=0.5):
        # This critical section is protected.
        run_expensive_daily_report()
except TimeoutError:
    # Failed to get the lock, another process is still working.
    print("Task is already running elsewhere.")


### Example 2: Manual acquire() / release() (Flexible/API Usage)

```python
db = BeaverDB("my_app.db")
lock = db.lock("my_task", timeout=10)

try:
    lock.acquire()
    # This critical section is protected.
    run_expensive_daily_report()
finally:
    lock.release()
```

## High-Level Implementation Plan

This feature will be built as a new, self-contained LockManager in a beaver/sync.py file. It will use its own dedicated table and will not be built on db.dict().

1. New Schema Table (beaver/core.py)
A new table, beaver_lock_waiters, will be added to _create_all_tables(). This table acts as a FIFO queue.
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

 * lock_name & requested_at: The composite PRIMARY KEY creates the fair (FIFO) queue.
 * waiter_id: A unique ID for the lock holder (e.g., "pid:123:ts:456").
 * expires_at: The time.time() timestamp. This is our deadlock-prevention mechanism.
2. New LockManager Class (beaver/sync.py)
This class will contain the core acquisition and release logic.
 * acquire(self):
   * Generates a unique _waiter_id.
   * Performs a single, O(1) INSERT to add itself to the beaver_lock_waiters queue with its waiter_id, requested_at = time.time(), and expires_at = time.time() + self._lock_ttl.
   * Enters a "polite polling" while True: loop.
   * Inside the loop (in a single transaction):
     * Step A (Cleanup): DELETE any waiters in the queue where expires_at < time.time(). This clears crashed processes.
     * Step B (Check): SELECT waiter_id FROM beaver_lock_waiters WHERE lock_name = ? ORDER BY requested_at ASC LIMIT 1.
   * If waiter_id == self._waiter_id: The process is now at the front of the queue and owns the lock. It return self.
   * If not: The process checks for timeout, then calls time.sleep(self._poll_interval).
 * release(self):
   * Performs a single, atomic, race-condition-free operation.
   * Executes DELETE FROM beaver_lock_waiters WHERE lock_name = ? AND waiter_id = ?.
   * This is an atomic Compare-and-Delete (CAS). It only removes its own entry, safely allowing the next process in the queue to acquire the lock on its next poll.
 * __enter__(self) and __exit__(self, ...):
   * __enter__ simply calls self.acquire().
   * __exit__ simply calls self.release().

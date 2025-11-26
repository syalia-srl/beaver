# Locks (Concurrency Control)

BeaverDB is designed to be **Process-Safe**. Multiple Python processes (e.g., web workers, scripts, background jobs) can read and write to the same database file simultaneously without corrupting it.

However, sometimes you need to synchronize *logic* across these processes. For example:
* "Only one worker should run the daily report generation."
* "Only one process should perform database compaction."
* "Wait until the current job is finished before starting the next."

The `LockManager` provides a simple, persistent, dead-lock safe locking primitive to handle these cases.

## Quick Start

Initialize a lock using `db.lock()`.

```python
from beaver import BeaverDB
import time

db = BeaverDB("app.db")

# 1. Define the critical section
# The lock name is global across all processes using this database file.
with db.lock("report_generation", timeout=10.0):
    print("Lock acquired! I am the only process running this block.")

    # Simulate work
    time.sleep(5)

    print("Work done. Releasing lock.")

# 2. Another process trying to acquire "report_generation"
# will wait here until the first process finishes or the timeout expires.
```

## How It Works

The lock is implemented using a persistent table in SQLite. It is:

  * **Fair (FIFO):** Processes are served in the order they requested the lock.
  * **Deadlock-Proof:** Every lock has a Time-To-Live (TTL). If a process crashes while holding a lock, the lock will automatically expire after the TTL, allowing other processes to proceed.
  * **Process-Aware:** It works across different scripts, terminals, or containers sharing the same `.db` file.

## Re-entrancy (Recursive Locking)

Unlike standard Python `threading.Lock`, a BeaverDB `Lock` instance is **re-entrant**. This means if you try to acquire the lock again *using the same object instance*, it will succeed immediately without blocking.

This design prevents self-deadlocks in complex code paths where a locked function calls another function that requires the same lock.

```python
lock = db.lock("resource")

with lock:
    print("Lock acquired.")

    # This works perfectly!
    # It detects that this specific 'lock' instance already holds it.
    with lock:
        print("Still holding the lock (Nested block).")
```

### Important: Instance vs. Name

Re-entrancy applies to the **Lock Object Instance**, not just the process.

If you create **two different lock objects** with the same name in the same process, they act as distinct waiters. The second one **will block** waiting for the first one to release.

```python
# Two distinct instances for the SAME resource
lock_a = db.lock("my_resource")
lock_b = db.lock("my_resource")

with lock_a:
    # This WILL BLOCK (and deadlock if no timeout is set)
    # because lock_b sees that "my_resource" is held by lock_a.
    with lock_b:
        pass
```

## Basic Operations

### Blocking Acquire

The default behavior is to block (wait) until the lock is available.

```python
# Waits forever until the lock is free
with db.lock("critical_resource"):
    process_resource()
```

### Timeout

You can specify a maximum wait time. If the lock isn't acquired by then, it raises a `TimeoutError`.

```python
try:
    # Wait up to 5 seconds
    with db.lock("resource", timeout=5.0):
        process()
except TimeoutError:
    print("Could not acquire lock. Resource is busy.")
```

### Non-Blocking Acquire

If you want to "try" to get the lock and fail immediately if it's taken (e.g., for a cron job that shouldn't overlap), use `block=False`.

```python
lock = db.lock("maintenance")

if lock.acquire(block=False):
    try:
        run_maintenance()
    finally:
        lock.release()
else:
    print("Maintenance is already running. Skipping.")
```

## Advanced Configuration

### Heartbeats (Renewing Locks)

If you have a long-running task (longer than the default TTL), you must periodically renew the lock to prevent it from expiring and letting another process in.

```python
lock = db.lock("long_task", lock_ttl=60) # 1 minute TTL

if lock.acquire():
    try:
        for i in range(10):
            do_step(i)
            # Extend the lock for another 60 seconds
            lock.renew(lock_ttl=60)
    finally:
        lock.release()
```

### Manual Cleanup

In rare cases (e.g., testing or admin intervention), you might want to forcibly break a lock held by another process.

```python
# Force-release the lock, kicking out any current holder
db.lock("stuck_job").clear()
```

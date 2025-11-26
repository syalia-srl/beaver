# Concurrency Model

BeaverDB is designed to be **Process-Safe** and **Thread-Safe**.

* **Process-Safe:** Multiple Python processes (workers, scripts) can access the same `.db` file simultaneously.
* **Thread-Safe:** Multiple threads within a single process can share the `BeaverDB` instance.

This capability relies on two pillars: **SQLite's WAL Mode** for data safety, and a custom **Lock Manager** for logical coordination.

## The SQLite Foundation (WAL Mode)

By default, BeaverDB enables **Write-Ahead Logging (WAL)** mode (`PRAGMA journal_mode=WAL`).

### Why WAL?

In standard SQLite (DELETE mode), a write operation locks the entire file, blocking all readers. This kills concurrency.

In **WAL mode**:
1.  **Writers** append changes to a separate `-wal` file.
2.  **Readers** read from the main `.db` file + the `-wal` file.
3.  **Result:** Readers do not block writers, and writers do not block readers.

This allows BeaverDB to handle high-throughput scenarios (e.g., a logger writing events while an API server queries them) without lock contention errors.

## Thread Safety (`threading.local`)

SQLite connections cannot be shared across threads. If two threads try to write to the same `sqlite3.Connection` object, the application will crash or corrupt memory.

BeaverDB manages this automatically using **Thread-Local Storage**.

```python
# Internal Logic
class BeaverDB:
    def __init__(self):
        self._thread_local = threading.local()

    @property
    def connection(self):
        # If this thread has never asked for a connection, open one.
        if not hasattr(self._thread_local, "conn"):
            self._thread_local.conn = sqlite3.connect(...)

        return self._thread_local.conn
```

  * When Thread A calls `db.dict("x")`, it gets a connection dedicated to Thread A.
  * When Thread B calls `db.dict("x")`, it gets a different connection dedicated to Thread B.
  * Both connections talk to the same file, mediated by SQLite's file locking.

## Logical Concurrency (`LockManager`)

SQLite handles *data* safety, but it doesn't handle *logical* safety.

**The Problem:**
Imagine two worker processes running a "Daily Cleanup" job. SQLite ensures they don't corrupt the file, but it doesn't stop them from running the cleanup logic twice, wasting CPU or sending duplicate emails.

**The Solution:**
BeaverDB implements a custom **Inter-Process Lock** stored in the database itself (`beaver_lock_waiters` table).

### Lock Algorithm

The `LockManager` implements a **Fair, Deadlock-Proof, FIFO Mutex**.

1.  **Request:** A process inserts a row into `beaver_lock_waiters` with a timestamp and a unique `waiter_id`.
2.  **Queue:** The table acts as a queue. The lock is "acquired" only if the process's row is the **oldest active row** for that lock name.
3.  **Poll:** If not at the front, the process sleeps (`poll_interval`) and checks again.
4.  **Safety (TTL):** Every lock has a `expires_at` timestamp. If a process crashes while holding the lock, other waiters will eventually see the expired row and delete it ("steal" the lock), preventing deadlocks.

```sql
-- Simplified Schema
CREATE TABLE beaver_lock_waiters (
    lock_name TEXT,
    waiter_id TEXT,
    requested_at REAL, -- Used for FIFO ordering
    expires_at REAL    -- Used for Deadlock protection
);
```

## Async Architecture

BeaverDB follows a **"Synchronous Core, Async Wrapper"** architecture.

  * **The Core:** All logic (`DictManager`, `LogManager`) is written in standard synchronous Python using `sqlite3`. This ensures simplicity and stability.
  * **The Async Layer:** Classes like `AsyncDictManager` or `AsyncLogManager` wrap the synchronous methods using `asyncio.to_thread()`.

### Why not pure `asyncio`?

Standard `sqlite3` is blocking. Even if you wrap it in `async def`, a query blocks the event loop. True non-blocking SQLite requires running the query in a separate thread.

BeaverDB automates this. When you call `await db.log("x").as_async().log(...)`, the operation is offloaded to a thread pool, keeping your `asyncio` loop responsive.

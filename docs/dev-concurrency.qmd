# Concurrency Model

**Chapter Outline:**

* **10.1. Thread Safety (`threading.local`)**
    * How BeaverDB provides a unique `sqlite3.Connection` for *every thread*.
    * Why this is the key to preventing thread-related errors.
    * Enabling WAL (Write-Ahead Logging) for concurrent reads.
* **10.2. Inter-Process Locking (The Implementation)**
    * How `db.lock()` works under the hood.
    * The `beaver_lock_waiters` table as a fair (FIFO) queue.
    * The `expires_at` column as a deadlock-prevention (TTL) mechanism.
* **10.3. The Asynchronous `.as_async()` Pattern**
    * How the `Async...Manager` wrappers are implemented.
    * Using `asyncio.to_thread` to run blocking I/O without blocking the event loop.

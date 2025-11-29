---
number: 25
title: "Refactor Core to Async-First Architecture with Sync Bridge"
state: closed
labels:
---

### 1. Concept

This feature proposes a fundamental architectural pivot for BeaverDB: moving from a **"Synchronous Core with Async Wrappers"** to an **"Async-First Core with a Synchronous Bridge"**.

Currently, features like `LockManager`, `ChannelManager` (Pub/Sub), and `LogManager.live()` rely on spawning dedicated Python threads and using blocking `time.sleep()` loops. This limits scalability (1,000 listeners = 1,000 threads) and increases resource overhead.

The new architecture will implement the core database logic using `asyncio` and `aiosqlite`. This allows thousands of concurrent listeners, locks, and background tasks to run on a single event loop with minimal overhead.

To preserve the existing synchronous API (`db = BeaverDB(...)`), we will implement the **"Portal Pattern"**: the synchronous `BeaverDB` class will start a single background thread running an `asyncio` loop and bridge all calls to it via `run_coroutine_threadsafe`.

### 2. Justification

* **Scalability:** Replaces heavy OS threads with lightweight `asyncio.Task` objects for polling and listening. BeaverDB will be able to handle thousands of concurrent `db.lock()` waiters or `db.channel().subscribe()` listeners without crashing the interpreter.
* **Efficiency:** Eliminates thread context-switching overhead for IO-bound operations.
* **Modernization:** Provides a native, first-class `AsyncBeaverDB` implementation for modern frameworks (FastAPI, Litestar) without the "sync-wrapper" performance penalty.
* **Simplified Thread Safety:** By serializing all logic through a single event loop thread, we eliminate complex `threading.local` connection management. The loop becomes the single source of truth.

### 3. Architecture Design

The system will be layered as follows:

1.  **Layer 1: Synchronous Facade (`beaver.core.BeaverDB`)**
    * The user-facing class.
    * Starts **one** background thread ("Reactor Thread") that runs an `asyncio` loop forever.
    * Methods like `.get()` or `.lock()` create a `Future`, schedule work on the Reactor Thread, and block until the result is ready.

2.  **Layer 2: Async Logic Core (`beaver.async_core.AsyncBeaverDB`)**
    * The new "real" database implementation.
    * Pure `async/await`.
    * Manages state, logic, and coordination.
    * Uses `await asyncio.sleep()` for polling (Locks, Queues), yielding control to the loop.

3.  **Layer 3: Async Storage (`aiosqlite`)**
    * Handles the actual SQL execution.
    * Manages its own internal thread pool to ensure blocking SQLite disk I/O does not freeze the Async Logic Core.

### 4. Implementation Plan

#### Phase 1: Dependencies & Core Setup
* Add `aiosqlite` as a core dependency.
* Create `beaver/async_core.py` containing the `AsyncBeaverDB` class.
* Implement `AsyncBeaverDB.connection` using `aiosqlite.connect`.

#### Phase 2: Refactor Polling Components
Rewrite the following components to be async-native within `beaver.async_core`:

* **`AsyncLockManager`:**
    * Replace `time.sleep(poll_interval)` with `await asyncio.sleep(poll_interval)`.
    * Logic remains identical (INSERT -> Sleep -> SELECT), ensuring process safety via SQLite WAL.
* **`AsyncChannelManager`:**
    * Replace the "1 thread per listener" model with an `asyncio.Condition` or `asyncio.Queue` pattern.
    * A single background task polls the DB and notifies all waiting coroutines.
* **`AsyncQueueManager`:**
    * Implement `.get()` using `await asyncio.sleep()` for the polling loop.

#### Phase 3: The Sync Bridge (`beaver.core.BeaverDB`)
Refactor the existing `BeaverDB` class to become a thin wrapper.

```python
class BeaverDB:
    def __init__(self, path: str):
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()

        # Initialize the real async DB on the loop
        future = asyncio.run_coroutine_threadsafe(AsyncBeaverDB(path), self._loop)
        self._async_db = future.result()

    def dict(self, name: str):
        # Returns a SyncDictManager that wraps AsyncDictManager
        return SyncDictManager(self._async_db.dict(name), self._loop)
```

#### Phase 4: Migration of Managers

Update all "Manager" classes to follow a dual structure:

1.  `AsyncListManager` (The implementation)
2.  `ListManager` (The sync wrapper that calls `run_coroutine_threadsafe` on the async version)

### 5\. Breaking Changes & Risks

  * **Blocking Operations:** While the sync API remains compatible, heavy operations (like Vector Search) running on the async core will block the event loop if not carefully managed by `aiosqlite`'s thread pool.
  * **Thread Local Storage:** We will remove `threading.local` connection management. This is a positive change but requires careful testing to ensure the new single-loop model doesn't introduce regressions in multi-threaded user apps.
# BeaverDB Feature Roadmap

This document contains a curated list of clever ideas and feature designs for the future development of `beaver-db`. The goal is to track innovative modalities that align with the library's core philosophy of being a simple, powerful, local-first database for AI prototyping.

## Feature: Comprehensive Async API with On-Demand Wrappers

### 1. Concept

A **Comprehensive Async API** will be introduced to allow seamless integration of `beaver-db` into modern `asyncio`-based applications. Instead of making the core library asynchronous, this feature will provide an elegant, on-demand way to get an async-compatible version of any core `beaver-db` object.

The core of the library will remain fully synchronous, respecting its design principle of a "Synchronous Core with Async Potential". The async functionality will be provided through thin, type-safe wrappers that run the blocking database calls in a background thread pool, ensuring the `asyncio` event loop is never blocked.

### 2. Use Cases

This feature is essential for developers using modern Python frameworks and for building highly concurrent applications:

  * **Modern Web Backends**: Natively integrate `beaver-db` with frameworks like FastAPI or Starlette without needing to manage a separate thread pool executor for database calls.
  * **High-Concurrency Tools**: Use `beaver-db` in applications that manage thousands of concurrent I/O operations (like websocket servers, scrapers, or chatbots) without sacrificing responsiveness.
  * **Ergonomic Developer Experience**: Allow developers working in an `async` codebase to use the familiar `await` syntax for all database operations, leading to cleaner and more consistent code.

### 3. Proposed API

The API is designed to be flexible and explicit, allowing the developer to "opt-in" to the async version of an object whenever needed.

  * `docs = db.collection("articles")`: The developer starts with the standard, synchronous object.
  * `async_docs = docs.as_async()`: A new `.as_async()` method on any synchronous wrapper (`CollectionWrapper`, `ListWrapper`, etc.) will return a parallel `Async` version of that object.
  * `await async_docs.index(my_doc)`: All methods on the `Async` wrapper are `async def` and must be awaited. The method names are identical to their synchronous counterparts, providing a clean and consistent API.
  * `await docs.as_async().search(vector)`: For one-off calls, the developer can chain the methods for a concise, non-blocking operation.

### 4. Implementation Design: Type-Safe Parallel Wrappers

The implementation will prioritize correctness, flexibility, and compatibility with developer tooling.

1.  **Parallel Class Hierarchy**: For each core wrapper (e.g., `CollectionWrapper`), there will be a corresponding `AsyncCollectionWrapper`. This new class will hold a reference to the original synchronous object.
2.  **Explicit `async def` Methods**: Every method on the `Async` wrapper will be explicitly defined with `async def`. This ensures that type checkers (like Mypy) and IDEs can correctly identify them as awaitable, preventing common runtime errors and providing proper autocompletion.
3.  **`asyncio.to_thread` Execution**: The implementation of each `async` method will simply call the corresponding synchronous method on the original object using `asyncio.to_thread`. This delegates the blocking I/O to a background thread, keeping the `asyncio` event loop free.

### 5. Alignment with Philosophy

This feature perfectly aligns with the library's guiding principles:

  * **Synchronous Core with Async Potential**: It adds a powerful `async` layer without altering the simple, robust, and synchronous foundation of the library.
  * **Simplicity and Pythonic API**: The `.as_async()` method is an intuitive and Pythonic way to opt into asynchronous behavior, and the chained-call syntax is elegant and clean.
  * **Developer Experience**: By ensuring the `async` wrappers are explicitly typed, the design prioritizes compatibility with modern developer tools, preventing bugs and improving productivity.

## Feature: Pydantic Model Integration for Type-Safe Operations

### 1. Concept

This feature will introduce optional, type-safe wrappers for `beaver-db`'s data structures, powered by Pydantic. By allowing developers to associate a Pydantic model with a dictionary, list, or queue, the library will provide automatic data validation, serialization, and deserialization. This enhances the developer experience by enabling static analysis and autocompletion in modern editors.

### 2. Use Cases

  * **Data Integrity**: Enforce a schema on your data at runtime, preventing corrupted or malformed data from being saved.
  * **Improved Developer Experience**: Get full autocompletion and type-checking in your IDE, reducing bugs and improving productivity.
  * **Automatic Serialization/Deserialization**: Seamlessly convert between Pydantic objects and JSON without boilerplate code.

### 3. Proposed API

The API is designed to be intuitive and "Pythonic", aligning with the existing design principles of the library.

```python
from pydantic import BaseModel
from beaver import BeaverDB

class Person(BaseModel):
    name: str
    age: int

db = BeaverDB("data.db")

# Dictionaries
users = db.dict("users", model=Person)
users["alice"] = Person(name="Alice", age=30)
alice = users["alice"] # Returns a Person object

# Lists
people = db.list("people", model=Person)
people.push(Person(name="Bob", age=40))
bob = people[0] # Returns a Person object

# Queues
tasks = db.queue("tasks", model=Person)
tasks.put(Person(name="Charlie", age=50), priority=1)
charlie_item = tasks.get()
charlie = charlie_item.data # Returns a Person object
```

### 4. Implementation Design: Generic Wrappers with Pydantic

The implementation will use Python's `typing.Generic` to create type-aware wrappers for the data structures.

  * **Generic Managers**: `DictManager`, `ListManager`, and `QueueManager` will be converted to generic classes (e.g., `ListManager(Generic[T])`).
  * **Serialization/Deserialization**: Internal `_serialize` and `_deserialize` methods will handle the conversion between Pydantic models and JSON strings.
  * **Optional Dependency**: `pydantic` will be an optional dependency, installable via `pip install "beaver-db[pydantic]"`, to keep the core library lightweight.

### 5. Alignment with Philosophy

This feature aligns with `beaver-db`'s guiding principles:

  * **Simplicity and Pythonic API**: The `model` parameter is a simple and intuitive way to enable type safety.
  * **Developer Experience**: This feature directly addresses the developer experience by providing type safety and editor support.
  * **Minimal & Cross-Platform Dependencies**: By making `pydantic` an optional dependency, the core library remains minimalistic.

## Feature: Drop-in REST API Client (`BeaverClient`)

### 1. Concept

This feature introduces a new `BeaverClient` class that acts as a **drop-in replacement** for the core `BeaverDB` class. Instead of interacting directly with a local SQLite file, this client will execute all operations by making requests to a remote BeaverDB REST API server. This allows users to seamlessly switch from a local, embedded database to a client-server architecture without changing their application code.

### 2. Use Cases

  * **Seamless Scaling**: Effortlessly transition a project from a local prototype to a networked service without a code rewrite.
  * **Multi-Process/Multi-Machine Access**: Allow multiple processes or machines to share and interact with a single, centralized BeaverDB instance.
  * **Language Interoperability**: While the client itself is Python, it provides a blueprint for creating clients in other languages to interact with the BeaverDB server.

### 3. Proposed API

The API is designed for maximum compatibility. A user only needs to change how the database object is instantiated.

**Local Implementation:**

```python
from beaver import BeaverDB
db = BeaverDB("my_local_data.db")
```

**Remote Implementation:**

```python
from beaver.client import BeaverClient
db = BeaverClient(base_url="http://127.0.0.1:8000")
```

All subsequent code, such as `db.dict("config")["theme"] = "dark"` or `db.collection("docs").search(...)`, remains identical.

### 4. Implementation Design: Remote Managers and HTTP Client

The implementation will live in a new `beaver/client.py` file and will not depend on any SQLite logic.

1.  **Core Component**: The `BeaverClient` class will manage a persistent HTTP session using the **`httpx`** library, which provides connection pooling and supports both synchronous and asynchronous operations.
2.  **Remote Managers**: For each existing manager (e.g., `DictManager`, `CollectionManager`), a corresponding `RemoteDictManager` or `RemoteCollectionManager` will be created. These classes will contain no database logic; their methods will simply construct and send the appropriate HTTP requests to the server endpoints.
3.  **WebSocket Handling**: For real-time features like `db.channel("my_channel").subscribe()` and `db.log("metrics").live()`, the remote managers will establish WebSocket connections to the server's streaming endpoints. This will require new `WebSocketSubscriber` and `WebSocketLiveIterator` classes that read from the network stream instead of a local queue.
4.  **Optional Dependency**: `httpx` and any necessary WebSocket libraries will be included as a new optional dependency, such as `pip install "beaver-db[client]"`.

### 5. Alignment with Philosophy

This feature strongly aligns with the library's guiding principles:

  * **Simplicity and Pythonic API**: By maintaining perfect API parity, it ensures the remote client is just as intuitive and simple to use as the local database.
  * **Developer Experience**: It provides a frictionless path for scaling applications, which is a major enhancement to the developer experience.
  * **Minimal Dependencies**: By keeping the client and its dependencies optional, the core library remains lightweight and dependency-free.

## Feature: Replace `faiss` with `numpy`-based Delta-Index

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

That's an excellent addition. Making the `poll_interval` a configurable parameter is the perfect way to manage the trade-off between responsiveness (a short interval) and I/O load (a long interval).

Here is the complete feature plan for the `roadmap.md` file, incorporating this final, robust design.

-----

## Feature: First-Class Inter-Process Synchronization (`db.lock`)

### 1\. Concept

This feature introduces a **first-class, inter-process synchronization primitive** to `beaver-db`, built directly on SQLite's atomic guarantees. It provides a simple, robust, and *fair* (FIFO) distributed lock that works across multiple, independent Python processes.

The primary motivation is to solve multi-process race conditions, such as the "thundering herd" problem where multiple processes might attempt to run the same expensive maintenance task (like vector compaction) simultaneously.

This `db.lock()` will serve as the **basic, fundamental synchronization strategy** for the library, from which users can build other complex coordination patterns. It is designed to be **deadlock-proof** (via TTL) and **starvation-proof** (via a FIFO queue).

### 2\. Use Cases

  * **Singleton Process Coordination:** Guarantee that only one process in a pool runs a specific, expensive task. This is the perfect solution for triggering the `NumpyVectorIndex.compact()` method safely.
  * **Critical Section Protection:** Allow any multi-process application to wrap a block of code in a `with` statement, ensuring that no other process can enter that block at the same time.
  * **Task Scheduling:** Enable a pool of workers to safely elect a "leader" to perform a scheduled task (e.g., "send the 9 AM daily report").

### 3\. Proposed API

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

### 4\. Implementation Design

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

### 5\. Alignment with Philosophy

This feature strongly supports the project's guiding principles.

  * **Simplicity and Pythonic API:** The `with db.lock(...):` syntax is the most intuitive and Pythonic way to handle resource locking.
  * **Minimal & Optional Dependencies:** This feature adds **zero new dependencies**. It is built entirely on the `sqlite3` standard library.
  * **Standard SQLite Compatibility:** The `beaver_lock_waiters` table is a standard, simple table that can be inspected and manually managed by any external SQLite tool, aligning with the "no-magic" data portability principle.
  * **Developer Experience:** It solves a hard, real-world concurrency problem (fairness, deadlocks, and races) with a simple, configurable, and robust tool.

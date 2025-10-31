---
number: 10
title: Expose `db.lock()` functionality on all high-level data managers
---

### 1. Concept

This feature proposes adding explicit, inter-process synchronization to all core state-mutating data managers: `DictManager`, `ListManager`, `CollectionManager`, **`QueueManager`**, and `BlobManager`.

This will be achieved by:

1.  Making each manager class a **Python context manager** (implementing `__enter__` and `__exit__`).
2.  Adding public `acquire()` and `release()` methods to each manager.
3.  Internally, these methods will be thin wrappers around the existing `db.lock()` primitive, using a reserved naming convention (e.g., `__lock__dict__<name>`).

This will allow users to perform complex, multi-step operations on a single data structure as a process-safe, atomic unit.

### 2. Use Cases

* **Atomic Read-Modify-Write (Dicts/Blobs):** Guarantee that a process can safely read, modify, and write a value back without another process interfering.
* **Batch Task Processing (Queues):** Allow a worker to **atomically retrieve a batch of multiple tasks** from the queue (e.g., calling `q.get()` five times) without another worker jumping in and stealing tasks in the middle of the batch operation.
* **List Manipulation (Lists):** Safely perform multi-step modifications like checking list length, popping the last item, and prepending a new item without race conditions.
* **Consistent State for Collections (Collections):** A process could lock a collection to perform a series of related operations (e.g., `index`, `drop`, and `connect`) and ensure that other processes only see the final, consistent state.

### 3. Proposed API

The primary change would be enabling a `with` statement directly on the manager object.

```python
db = BeaverDB("my.db")

# Example for a Dictionary (Atomic Read-Modify-Write)
try:
    with db.dict("config", timeout=5) as config:
        count = config.get("counter", 0)
        count += 1
        config["counter"] = count
except TimeoutError:
    print("Could not acquire lock for config.")

# Example for a Queue (Atomic Batch Processing)
try:
    with db.queue("tasks", timeout=10) as q:
        task1 = q.get()
        task2 = q.get()
        print(f"Retrieved two tasks atomically: {task1} and {task2}")
except IndexError:
    print("Queue did not have two tasks.")
except TimeoutError:
    print("Could not acquire lock for queue.")
```

### 4. Implementation Design (High-Level)

1.  **Manager `__init__` Modification:**

* The `__init__` method for all targeted managers (`DictManager`, `ListManager`, `CollectionManager`, **`QueueManager`**, and `BlobManager`) will be updated.
* Each manager will initialize and store an internal `LockManager` instance, which is provided by `db.lock()`.
* The lock name will use a standardized internal format based on the manager type and the manager's name, e.g., `f"__lock__queue__{self._name}"`.

1.  **Lock Methods Implementation:**

* `acquire(self, timeout=None, ...)`: Calls `self._lock.acquire(timeout=timeout, ...)` internally.
* `release(self)`: Calls `self._lock.release()` internally.
* `__enter__(self)`: Calls `self.acquire()`.
* `__exit__(self, exc_type, exc_val, exc_tb)`: Calls `self.release()`.

1.  **Targeted Manager Classes:**

* `DictManager` (`beaver/dicts.py`)
* `ListManager` (`beaver/lists.py`)
* **`QueueManager`** (`beaver/queues.py`)
* `CollectionManager` (`beaver/collections.py`)
* `BlobManager` (`beaver/blobs.py`)

1.  **Exclusions:** `ChannelManager` and `LogManager` will **not** be modified, as their core write operations are already atomic, and imposing a lock would create an unnecessary performance bottleneck for their high-concurrency design.

### 5. Alignment with Philosophy

This feature aligns with `beaver-db`'s core principles:

* **Simplicity and Pythonic API:** Provides the most intuitive `with` statement syntax for concurrency control.
* **Developer Experience:** Solves complex multi-process problems (like batch race conditions) with a simple, high-level primitive.
* **Synchronous Core:** Builds entirely on the existing, dependency-free `db.lock()` primitive, maintaining the project's architectural integrity.
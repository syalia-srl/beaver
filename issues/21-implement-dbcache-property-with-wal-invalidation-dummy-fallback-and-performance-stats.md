---
number: 21
title: "Implement `db.cache` Property with WAL Invalidation, Dummy Fallback, and Performance Stats"
state: open
labels:
---

### 1. Justification

The current BeaverDB implementation performs a database I/O and `json.loads` operation for *every* data-access method [cite: beaver/dicts.py, beaver/lists.py]. This is robust but creates a performance bottleneck for read-heavy applications, especially in the common single-process use case.

This feature introduces a **process-local, thread-local, in-memory read cache** to make subsequent reads of the same data instantaneous.

All caching logic will be encapsulated into a unified cache interface, which will be provided to managers via a new `db.cache` property:

1.  If caching is enabled (`cache_enabled=True`), this property will return a "real" `ThreadLocalCache` instance.
2.  If caching is disabled (`cache_enabled=False`), it will return a `DummyCache` instance.

This **Null Object Pattern** is critical: it **eliminates all conditional `if cache is not None:` logic** from the data managers, as they can call `cache.get(key)` and `cache.set(key, value)` unconditionally.

The `ThreadLocalCache` instance will be "smart," automatically monitoring the `mtime` of the SQLite Write-Ahead Log (`-wal`) file [cite: beaver/core.py] and invalidating itself on the next read if a write is detected from another process.

Finally, the cache objects will track their own performance statistics, allowing developers to introspect cache effectiveness.

### 2. Use Cases

  * **Single-Process Speed:** A script that repeatedly reads `db.dict("config")["key"]` will only hit the database on the first read. All subsequent reads will be at memory speed.
  * **Clean & Simple Manager Logic:** Data managers (`DictManager`, `ListManager`) no longer need any `if` statements for caching. They just call `self._db.cache.get(key)` and `self._db.cache.set(key, value)` unconditionally.
  * **Multi-Process Safety:** The cache is automatically and safely invalidated when another process writes to the database, preventing stale data reads.
  * **Performance Tuning:** A developer can call `db.cache.stats()` to get a `CacheStats` object, allowing them to measure the `hit_rate` and `invalidation_rate` of their application's read patterns.

### 3. Proposed API & Implementation Design

This implementation is centered on a new cache interface and a factory property on `BeaverDB`.

#### B. `BeaverDB` Class Modifications (in `beaver/core.py`)

1.  **`__init__`:**

      * Add `cache_enabled: bool = True` parameter and store it.
      * Store `self._wal_path = f"{self._db_path}-wal"`.
      * `from .cache import ThreadLocalCache, DummyCache, ICache, CacheStats`
      * Create a single, class-level dummy instance: `_dummy_cache_instance = DummyCache()`

2.  **`connection` Property:**

      * When initializing a new thread-local connection [cite: beaver/core.py], also initialize the cache instance:
        ```python
        # ... (inside if conn is None:)
        if self._cache_enabled:
            self._thread_local.cache = ThreadLocalCache(self._wal_path)
        else:
            self._thread_local.cache = BeaverDB._dummy_cache_instance
        # ...
        ```

3.  **New `cache` Property:**

      * This property simply retrieves the correct thread-safe cache instance.

    <!-- end list -->

    ```python
    @property
    def cache(self) -> ICache:
        """
        Returns the thread-local cache instance.
        This will be a ThreadLocalCache if enabled, or a DummyCache if disabled.
        The returned object is guaranteed to have .get, .set, .pop, .clear, and .stats methods.
        """
        # Ensure connection (and thus cache) is initialized for this thread
        if not hasattr(self._thread_local, "conn"):
            _ = self.connection

        return self._thread_local.cache
    ```

#### C. Simplified Manager Logic (e.g., `beaver/dicts.py`)

The data managers no longer contain any `if cache...` logic.

  * **Read Path (`DictManager.__getitem__` [cite: beaver/dicts.py]):**

    ```python
    def __getitem__(self, key: str) -> T:
        cache_key = f"dict_{self._name}_{key}"
        cached_value = self._db.cache.get(cache_key) # get() handles invalidation + stats

        if cached_value is not None:
            return cached_value  # Cache HIT

        # Cache MISS: Proceed with existing database logic
        # ... (cursor = self._db.connection.cursor() ...)
        # ... (fetch value, check expiry, etc.) ...

        deserialized_value = self._deserialize(value)

        self._db.cache.set(cache_key, deserialized_value) # Populate cache
        return deserialized_value
    ```

  * **Write Path (`DictManager.__setitem__` [cite: beaver/dicts.py]):**

    ```python
    def __setitem__(self, key: str, value: T, ...):
        # ... (Perform database write: self._db.connection.execute(...)) ...

        cache_key = f"dict_{self._name}_{key}"
        self._db.cache.set(cache_key, value) # Write-through (updates mtime)
    ```

  * **Eviction Path (`DictManager.__delitem__` [cite: beaver/dicts.py]):**

    ```python
    def __delitem__(self, key: str):
        # ... (Perform database delete: cursor.execute("DELETE ...")) ...

        cache_key = f"dict_{self._name}_{key}"
        self._db.cache.pop(cache_key) # Evict from cache (updates mtime)
    ```

### 5. High-Level Roadmap

1.  **Phase 1: Implement Cache Classes (`beaver/cache.py`)**

      * Create the new `beaver/cache.py` file.
      * Implement the `CacheStats` `NamedTuple` with its properties.
      * Implement the `ICache` protocol.
      * Implement the `DummyCache` class.
      * Implement the `ThreadLocalCache` class with all its `mtime` logic and statistics counters.

2.  **Phase 2: Factory Logic in `BeaverDB` (`beaver/core.py`)**

      * Add `cache_enabled` to `BeaverDB.__init__` [cite: beaver/core.py].
      * Create the `_dummy_cache_instance`.
      * Modify the `BeaverDB.connection` property to create and store the correct cache instance (real or dummy) on `self._thread_local`.
      * Implement the new `BeaverDB.cache` property that returns `self._thread_local.cache`.

3.  **Phase 3: Refactor Managers (Read/Write/Delete)**

      * **`DictManager` / `BlobManager`:** Refactor `get`/`__getitem__`, `set`/`put`, and `del`/`delete`/`pop` to use `self._db.cache.get/set/pop` unconditionally [cite: beaver/dicts.py, beaver/blobs.py].
      * **`QueueManager`:** Refactor `peek` to use `cache.get`. Refactor `put` and `get` to call `cache.clear()` (as they invalidate the "peek" key) [cite: beaver/queues.py].
      * **`ListManager`:** Refactor `__getitem__` (for *integer indexes only*) to use `cache.get`. For *all write/delete operations* (`push`, `pop`, `insert`, `__setitem__`, `__delitem__` [cite: beaver/lists.py]), call `cache.clear()` to invalidate the entire list cache.

4.  **Phase 4: Test Implementation**

      * Add unit tests for `ThreadLocalCache` and `DummyCache`, ensuring `stats()` works as expected.
      * Add an integration test with `cache_enabled=True` to verify that `db.cache.stats().hits` increases on a second read.
      * Add an integration test with `cache_enabled=False` to verify that `db.cache.stats().hits` remains 0 (i.e., `DummyCache` is working).
      * Add a `multiprocessing` test to verify that a write from **Process A** correctly triggers an `invalidation` count in **Process B**'s cache stats.
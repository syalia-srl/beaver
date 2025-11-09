import os
import functools
import threading
import time
from typing import Optional, Any, Protocol, NamedTuple


class CacheStats(NamedTuple):
    """Holds performance metrics for a cache instance."""

    hits: int
    misses: int
    invalidations: int
    sets: int
    pops: int

    @property
    def reads(self) -> int:
        return self.hits + self.misses

    @property
    def operations(self) -> int:
        return self.hits + self.misses + self.sets + self.pops

    @property
    def hit_rate(self) -> float:
        """Returns the cache hit rate (0.0 to 1.0)."""
        if self.reads == 0:
            return 0.0

        return self.hits / self.reads

    @property
    def invalidation_rate(self) -> float:
        """Returns the rate of invalidations per operation (0.0 to 1.0)."""
        if self.reads == 0:
            return 0.0

        return self.invalidations / self.operations


class ICache(Protocol):
    """Defines the public interface for all cache objects."""

    def get(self, key: str) -> Optional[Any]: ...
    def set(self, key: Any, value: Any): ...
    def pop(self, key: str): ...
    def invalidate(self): ...
    def stats(self) -> CacheStats: ...
    def touch(self): ...


class DummyCache:
    """A cache object that does nothing. Used when caching is disabled."""

    _stats = CacheStats(hits=0, misses=0, invalidations=0, sets=0, pops=0)

    def get(self, key: str) -> Optional[Any]:
        return None

    def set(self, key: str, value: Any):
        pass

    def pop(self, key: str):
        pass

    def invalidate(self):
        pass

    def stats(self) -> CacheStats:
        return self._stats

    @classmethod
    def singleton(cls) -> ICache:
        if not hasattr(cls, "__instance"):
            cls.__instance = cls()

        return cls.__instance

    def touch(self):
        pass

class LocalCache:
    """
    A thread-local cache that invalidates based on a central,
    database-backed version number, checking only once per interval.
    """
    def __init__(
        self,
        db,
        cache_namespace: str,
        check_interval: float
    ):
        from .types import IDatabase

        self._db: IDatabase = db
        self._data: dict[str, Any] = {}
        self._lock = threading.Lock()

        self._version_key: str = cache_namespace # e.g., "list:tasks"
        self._local_version: int = -1
        self._last_check_time: float = 0.0
        self._min_check_interval: float = check_interval

        # Statistics
        self._hits = 0
        self._misses = 0
        self._invalidations = 0
        self._sets = 0
        self._pops = 0
        self._clears = 0

    def _get_global_version(self) -> int:
        """Reads the 'source of truth' version from the DB."""
        # This is a raw, direct DB call to avoid circular dependencies
        cursor = self._db.connection.cursor()
        cursor.execute(
            "SELECT version FROM beaver_manager_versions WHERE namespace = ?",
            (self._version_key,)
        )
        result = cursor.fetchone()
        return int(result[0]) if result else 0

    def _check_and_invalidate(self):
        """
        Checks if the cache is stale, but only hits the DB
        once per check_interval.
        """
        now = time.time()

        # --- 1. The Hot Path (Pure In-Memory Check) ---
        if (now - self._last_check_time) < self._min_check_interval:
            return

        # --- 2. The "Coalesced" DB Check ---
        with self._lock:
            # Double-check inside lock in case another thread just ran this
            if (time.time() - self._last_check_time) < self._min_check_interval:
                return

            global_version = self._get_global_version()
            self._last_check_time = time.time() # Reset timer

            if global_version != self._local_version:
                self._data.clear()
                self._local_version = global_version
                self._invalidations += 1

    def get(self, key: str) -> Optional[Any]:
        # This check is now extremely fast
        self._check_and_invalidate()

        with self._lock:
            value = self._data.get(key)

            if value is not None:
                self._hits += 1
                return value

            self._misses += 1

        return None

    def set(self, key: str, value: Any):
        with self._lock:
            self._data[key] = value
            self._sets += 1

    def pop(self, key: str):
        with self._lock:
            self._data.pop(key, None)
            self._pops += 1

    def invalidate(self):
        with self._lock:
            self._data.clear()
            self._local_version = 0 # Must force re-check
            self._invalidations += 1
            self._last_check_time = 0.0

    def touch(self):
        """
        Atomically increments the cache version in the native SQL table
        and syncs the cache's local version to avoid self-invalidation.

        Only call this when you make a change that should invalidate
        other caches of the same namespace in other processes,
        but keep this cache valid.
        """
        with self._lock:
            new_version = 0

            with self._db.connection:
                # This is a single, atomic, native SQL operation.
                cursor = self._db.connection.execute(
                    """
                    INSERT INTO beaver_manager_versions (namespace, version)
                    VALUES (?, 1)
                    ON CONFLICT(namespace) DO UPDATE SET
                        version = version + 1
                    RETURNING version;
                    """,
                    (self._version_key,)
                )
                new_version = cursor.fetchone()[0]

            # Keep the cache in sync to avoid self-invalidation
            self._last_check_time = time.time()
            self._local_version = new_version

    def stats(self) -> CacheStats:
        return CacheStats(
            hits=self._hits,
            misses=self._misses,
            invalidations=self._invalidations,
            sets=self._sets,
            pops=self._pops,
        )

    def __repr__(self) -> str:
        return f"<LocalCache namespace='{self._version_key}', version={self._local_version}>"


def cached(key):
    """
    Decorator for read methods.
    - Generates a cache key using key on the arguments.
    - If key is None, bypasses cache.
    - If key is in cache, returns cached value.
    - If key is not in cache, runs the decorated function,
      stores the result, and returns it.
    """
    from .manager import ManagerBase

    def decorator(func):
        @functools.wraps(func)
        def wrapper(self: ManagerBase, *args, **kwargs):
            cache = self.cache
            cache_key = key(*args, **kwargs)

            if cache_key is None:
                return func(self, *args, **kwargs)

            if not self.locked:
                cached_value = cache.get(cache_key)

                if cached_value is not None:
                    return cached_value  # HIT

            result = func(self, *args, **kwargs)
            cache.set(cache_key, result)

            return result
        return wrapper
    return decorator


def invalidates_cache(func):
    """
    Decorator for write methods that need to invalidate cache.
    - Runs the decorated function.
    - Clears the cache even if there is any exception.
    """
    from .manager import ManagerBase

    @functools.wraps(func)
    def wrapper(self: "ManagerBase", *args, **kwargs):
        try:
            result = func(self, *args, **kwargs)
        finally:
            self.cache.invalidate()

        return result

    return wrapper

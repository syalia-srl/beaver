import os
import functools
from typing import Optional, Any, Protocol, NamedTuple


class CacheStats(NamedTuple):
    """Holds performance metrics for a cache instance."""

    hits: int
    misses: int
    invalidations: int
    sets: int
    pops: int
    clears: int

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
    def set(self, key: str, value: Any): ...
    def pop(self, key: str): ...
    def clear(self): ...
    def stats(self) -> CacheStats: ...


class DummyCache:
    """A cache object that does nothing. Used when caching is disabled."""

    _stats = CacheStats(hits=0, misses=0, invalidations=0, sets=0, pops=0, clears=0)

    def get(self, key: str) -> Optional[Any]:
        return None

    def set(self, key: str, value: Any):
        pass

    def pop(self, key: str):
        pass

    def clear(self):
        pass

    def stats(self) -> CacheStats:
        return self._stats

    @classmethod
    def singleton(cls) -> ICache:
        if not hasattr(cls, "__instance"):
            cls.__instance = cls()

        return cls.__instance


class LocalCache:
    """A thread-local cache that self-invalidates by checking WAL mtime."""

    def __init__(self, wal_path: str):
        self._wal_path = wal_path
        self._data: dict[str, Any] = {}
        self._last_known_wal_mtime: float = self._get_wal_mtime()

        # Statistics
        self._hits = 0
        self._misses = 0
        self._invalidations = 0
        self._sets = 0
        self._pops = 0
        self._clears = 0

    def _get_wal_mtime(self) -> float:
        try:
            return os.stat(self._wal_path).st_mtime
        except FileNotFoundError:
            return 0.0

    def _check_and_invalidate(self):
        current_wal_mtime = self._get_wal_mtime()

        if current_wal_mtime > self._last_known_wal_mtime:
            self._data.clear()
            self._last_known_wal_mtime = current_wal_mtime
            self._invalidations += 1

    def _update_mtime_after_write(self):
        self._last_known_wal_mtime = self._get_wal_mtime()

    def get(self, key: str) -> Optional[Any]:
        self._check_and_invalidate()
        value = self._data.get(key)

        if value is not None:
            self._hits += 1
            return value

        self._misses += 1
        return None

    def set(self, key: str, value: Any):
        self._data[key] = value
        self._update_mtime_after_write()
        self._sets += 1

    def pop(self, key: str):
        self._data.pop(key, None)
        self._update_mtime_after_write()
        self._pops += 1

    def clear(self):
        self._data.clear()
        self._update_mtime_after_write()
        self._clears += 1

    def stats(self) -> CacheStats:
        return CacheStats(
            hits=self._hits,
            misses=self._misses,
            invalidations=self._invalidations,
            sets=self._sets,
            pops=self._pops,
            clears=self._clears,
        )


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
            cache_key = key(self, *args, **kwargs)

            if cache_key is None:
                return func(self, *args, **kwargs)

            cached_value = cache.get(cache_key)

            if cached_value is not None:
                return cached_value  # HIT

            try:
                result = func(self, *args, **kwargs)
                cache.set(cache_key, result)
            except Exception:
                raise

            return result
        return wrapper
    return decorator

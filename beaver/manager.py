import json
import functools
import sqlite3
from typing import Type, Optional, Any, Self
from .types import IDatabase, JsonSerializable
from .locks import LockManager
from .cache import ICache


class ManagerBase[T: JsonSerializable]:
    """
    Base class for data managers, providing common locking,
    caching, and serialization logic.
    """

    def __init__(self, name: str, db: IDatabase, model: Type[T] | None = None):
        """
        Initializes the base manager.

        Args:
            name: The user-provided name for the data structure.
            db: The BeaverDB database instance.
            model: The optional model for serialization.
        """
        # Automatically determine the prefix from the child class name
        # e.g., "ListManager" -> "list"
        manager_type_prefix = self.__class__.__name__.replace("Manager", "").lower()

        if not isinstance(name, str) or not name:
            raise TypeError(f"{manager_type_prefix.capitalize()} name must be a non-empty string.")

        self._name = name
        self._db = db
        self._model = model
        self._cache_key = f"{manager_type_prefix}:{self._name}"

        # Public lock for batch operations (from Issue #10)
        public_lock_name = f"__lock__{manager_type_prefix}__{name}"
        self._lock = LockManager(db, public_lock_name)

        # Internal lock for atomic methods (from Issue #17)
        internal_lock_name = f"__internal_lock__{manager_type_prefix}__{name}"
        self._internal_lock = LockManager(
            db,
            internal_lock_name,
            timeout=1.0,  # Short timeout for internal operations
            lock_ttl=5.0 # Short TTL to clear crashes
        )

    @property
    def connection(self) -> sqlite3.Connection:
        """
        Returns the thread-safe SQLite connection from the core DB instance.
        """
        return self._db.connection

    @property
    def cache(self) -> ICache:
        """
        Returns the thread-local cache for this manager.
        """
        return self._db.cache(self._cache_key)

    def _serialize(self, value: T) -> str:
        """
        Serializes the given value to a JSON string.
        """
        if isinstance(value, JsonSerializable):
            return value.model_dump_json()

        return json.dumps(value)

    def _deserialize(self, value: str) -> T:
        """
        Deserializes a JSON string into the specified model or a generic object.
        """
        if self._model:
            return self._model.model_validate_json(value)

        return json.loads(value)

    # --- Public Lock Interface ---

    def acquire(
        self,
        timeout: Optional[float] = None,
        lock_ttl: Optional[float] = None,
        poll_interval: Optional[float] = None,
        block: bool = True,
    ) -> bool:
        """
        Acquires the public inter-process lock on this manager.
        [cite: issues/closed/10-expose-dblock-functionality-on-all-high-level-data-managers.md]

        Parameters and behavior the same as `LockManager.acquire()`.
        """
        return self._lock.acquire(
            timeout=timeout,
            lock_ttl=lock_ttl,
            poll_interval=poll_interval,
            block=block,
        )

    def release(self):
        """
        Releases the public inter-process lock on this manager.
        """
        self._lock.release()

    def renew(self, lock_ttl: Optional[float] = None) -> bool:
        """
        Renews the TTL (heartbeat) of the public lock held by this instance.

        Returns:
            True if the lock was held and renewed, False otherwise.
        """
        return self._lock.renew(lock_ttl)

    def __enter__(self) -> Self:
        """
        Acquires the public lock upon entering a 'with' statement.
        Raises TimeoutError if the lock cannot be acquired.
        [cite: issues/closed/10-expose-dblock-functionality-on-all-high-level-data-managers.md, beaver/locks.py]
        """
        if self.acquire():
            return self

        raise TimeoutError(f"Failed to acquire public lock for '{self._name}'")

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Releases the public lock when exiting a 'with' statement.
        """
        self.release()


def synced(func):
    """
    A decorator to wrap a manager method in the manager's *internal* lock
    and a database transaction.

    This ensures the entire method is both an atomic, process-safe operation
    (via the lock) and an ACID-compliant transaction (via the connection).
    """
    @functools.wraps(func)
    def wrapper(self: ManagerBase, *args, **kwargs):
        """Wraps the function in the internal lock and a transaction."""

        # 1. Acquire the inter-process lock
        with self._internal_lock:
            # 2. Begin an ACID database transaction
            with self.connection:
                # 3. Execute the original method
                return func(self, *args, **kwargs)

    return wrapper

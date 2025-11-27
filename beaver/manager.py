import json
import functools
import weakref
from typing import Callable, Type, Optional, Self, Any, TYPE_CHECKING
import aiosqlite
from pydantic import BaseModel

from .locks import AsyncBeaverLock

# Forward reference for type checking to avoid circular imports
if TYPE_CHECKING:
    from .core import AsyncBeaverDB
    from .cache import ICache


class EventHandle:
    """
    Public-facing handle returned by `AsyncBeaverBase.on()`.
    Allows the user to close their specific callback listener.
    """

    def __init__(
        self,
        db: "AsyncBeaverDB",
        topic: str,
        event: str,
        callback: Callable,
    ):
        self._db_ref = weakref.ref(db)
        self._topic = topic
        self._event = event
        self._callback = callback
        self._closed = False

    async def off(self):
        """Removes the callback from the central registry."""
        if self._closed:
            return

        db = self._db_ref()
        # db.off() implementation deferred to Phase 4
        if db and hasattr(db, "off"):
            await db.off(self._topic, self._event, self._callback)

        self._closed = True


class AsyncBeaverBase[T: BaseModel]:
    """
    Base class for async data managers.
    Handles serialization, locking, and basic connection access.
    """

    def __init__(self, name: str, db: "AsyncBeaverDB", model: Type[T] | None = None):
        """
        Initializes the base manager.
        """
        # Automatically determine the prefix from the child class name
        # e.g., "AsyncBeaverList" -> "list"
        # e.g., "DictManager" (Legacy) -> "dict"
        cls_name = self.__class__.__name__
        if "AsyncBeaver" in cls_name:
            manager_type_prefix = cls_name.replace("AsyncBeaver", "").lower()
        else:
            manager_type_prefix = cls_name.replace("Manager", "").lower()

        if not isinstance(name, str) or not name:
            raise TypeError(
                f"{manager_type_prefix.capitalize()} name must be a non-empty string."
            )

        self._name = name
        self._db = db
        self._model = model
        self._topic = f"{manager_type_prefix}:{self._name}"

        # Public lock for batch operations
        public_lock_name = f"__lock__{manager_type_prefix}__{name}"
        self._lock = AsyncBeaverLock(db, public_lock_name)

        # Internal lock for atomic methods
        internal_lock_name = f"__internal_lock__{manager_type_prefix}__{name}"
        self._internal_lock = AsyncBeaverLock(
            db,
            internal_lock_name,
            timeout=5.0,  # Short timeout for internal operations
            lock_ttl=5.0,  # Short TTL to clear crashes
        )

    @property
    def locked(self) -> bool:
        """Returns whether the current manager is locked by this process."""
        return self._lock._acquired

    @property
    def connection(self) -> aiosqlite.Connection:
        """Returns the shared async connection."""
        return self._db.connection

    @property
    def cache(self) -> "ICache":
        """Returns the thread-local cache for this manager (Stub)."""
        return self._db.cache(self._topic)

    def _serialize(self, value: T) -> str:
        """Serializes the given value to a JSON string (Sync CPU bound)."""
        if isinstance(value, BaseModel):
            return value.model_dump_json()

        return json.dumps(value)

    def _deserialize(self, value: str) -> T:
        """Deserializes a JSON string (Sync CPU bound)."""
        if self._model:
            return self._model.model_validate_json(value)

        return json.loads(value)

    # --- Public Lock Interface ---

    async def acquire(
        self,
        timeout: Optional[float] = None,
        lock_ttl: Optional[float] = None,
        poll_interval: Optional[float] = None,
        block: bool = True,
    ) -> bool:
        """Acquires the public inter-process lock on this manager."""
        return await self._lock.acquire(
            timeout=timeout,
            lock_ttl=lock_ttl,
            poll_interval=poll_interval,
            block=block,
        )

    async def release(self):
        """Releases the public inter-process lock on this manager."""
        await self._lock.release()

    async def renew(self, lock_ttl: Optional[float] = None) -> bool:
        """Renews the TTL (heartbeat) of the public lock."""
        return await self._lock.renew(lock_ttl)

    async def __aenter__(self) -> Self:
        """Async Context Manager for public locking."""
        if await self.acquire():
            return self
        raise TimeoutError(f"Failed to acquire public lock for '{self._name}'")

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.release()

    # --- Events (Stubs for Phase 4) ---

    def on(self, event: str, callback: Callable) -> EventHandle:
        """
        Subscribes to an event. (Placeholder implementation)
        """
        # self._db.on() call deferred to Phase 4
        return EventHandle(self._db, self._topic, event, callback)


def atomic(func):
    """
    A decorator to wrap a manager method in the manager's *internal* lock
    AND a database transaction.

    This ensures:
    1. Process Safety: Via AsyncBeaverLock (internal)
    2. Thread Safety: Via AsyncBeaverDB.transaction() (asyncio.Lock)
    3. ACID: Via SQLite 'BEGIN IMMEDIATE'
    """

    @functools.wraps(func)
    async def wrapper(self: AsyncBeaverBase, *args, **kwargs):
        # 1. Acquire Process Lock (Wait for other processes)
        async with self._internal_lock:
            # 2. Acquire Transaction Lock (Wait for other local tasks)
            # This is crucial for aiosqlite shared connections!
            async with self._db.transaction():
                return await func(self, *args, **kwargs)

    return wrapper


def emits(event: str | None = None, payload: Callable | None = None):
    """
    A decorator to emit an event after a manager method completes.
    Updated to work with async functions.
    """

    def decorator(func):
        event_name = event or func.__name__
        payload_func = payload or (lambda *args, **kwargs: dict(args=args, **kwargs))

        @functools.wraps(func)
        async def wrapper(self, *args, **kwargs):
            payload_data = payload_func(*args, **kwargs)

            # Execute the actual async operation
            result = await func(self, *args, **kwargs)

            # Emit event (Check if DB supports emit, defer to Phase 4)
            if hasattr(self._db, "emit"):
                # If emit is async in the future:
                # await self._db.emit(self._topic, event_name, payload_data)
                # For now, we assume it's stubbed or missing.
                pass

            return result

        return wrapper

    return decorator

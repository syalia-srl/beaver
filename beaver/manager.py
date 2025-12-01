import json
import functools
from typing import Callable, Type, Optional, Self, Any, TYPE_CHECKING

from pydantic import BaseModel

from .locks import AsyncBeaverLock

# Forward reference for type checking to avoid circular imports
if TYPE_CHECKING:
    from .core import AsyncBeaverDB
    from .cache import ICache
    from .events import AsyncBeaverEvents, EventHandler


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
        cls_name = self.__class__.__name__
        manager_type_prefix = cls_name.replace("AsyncBeaver", "").lower()

        if not isinstance(name, str) or not name:
            raise TypeError(
                f"{manager_type_prefix.capitalize()} name must be a non-empty string."
            )

        self._name = name
        self._db = db
        self._model = model
        self._topic = f"{manager_type_prefix}:{self._name}"

        # Lazy-loaded event manager
        self._event_manager: "AsyncBeaverEvents | None" = None

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
    def connection(self) -> Any:
        """Returns the shared async connection."""
        return self._db.connection

    @property
    def cache(self) -> "ICache":
        """Returns the thread-local cache for this manager (Stub)."""
        return self._db.cache(self._topic)

    @property
    def events(self) -> "AsyncBeaverEvents":
        """
        Returns the Event Manager attached to this data structure.
        Lazy-loaded to avoid circular imports during init.
        """
        if self._event_manager is None:
            # Import here to avoid circular dependency loop
            from .events import AsyncBeaverEvents

            # We create an event manager scoped to this manager's unique topic name
            # This ensures events like "set" are unique to THIS dictionary instance.
            # We use the same model T so event payloads are typed correctly if applicable.
            self._event_manager = AsyncBeaverEvents(
                name=self._topic, db=self._db, model=self._model
            )

        return self._event_manager

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

    # --- Events Portal ---

    async def on(self, event: str, callback: Callable) -> "EventHandler":
        """
        Subscribes to an event on this manager (e.g. "set", "push").
        This is a convenience wrapper around self.events.attach().
        """
        return await self.events.attach(event, callback)

    async def off(self, event: str, callback: Callable):
        """
        Unsubscribes from an event.
        Convenience wrapper around self.events.detach().
        """
        await self.events.detach(event, callback)


def atomic(func):
    """
    A decorator to wrap a manager method in the manager's *internal* lock
    AND a database transaction.
    """

    @functools.wraps(func)
    async def wrapper(self: AsyncBeaverBase, *args, **kwargs):
        async with self._internal_lock:
            async with self._db.transaction():
                return await func(self, *args, **kwargs)

    return wrapper


def emits(event: str | None = None, payload: Callable | None = None):
    """
    A decorator to emit an event after a manager method completes.
    Uses the manager's attached Event Bus.
    """

    def decorator(func):
        event_name = event or func.__name__
        payload_func = payload or (lambda *args, **kwargs: dict(args=args, **kwargs))

        @functools.wraps(func)
        async def wrapper(self: AsyncBeaverBase, *args, **kwargs):
            # Calculate payload BEFORE mutation (to capture args)
            # or AFTER? Usually we want the *result* or the *input*.
            # The current lambda often uses args.

            # Execute the actual async operation
            result = await func(self, *args, **kwargs)

            # PERFORMANCE FIX: Only emit if the event manager has been initialized.
            # This prevents starting the background polling loop for every manager
            # unless the user has explicitly attached a listener (which inits the manager).
            if self._event_manager is not None:
                try:
                    payload_data = payload_func(*args, **kwargs)
                    # We await it to ensure the event is persisted to the log before returning
                    await self._event_manager.emit(event_name, payload_data)
                except Exception:
                    pass

            return result

        return wrapper

    return decorator

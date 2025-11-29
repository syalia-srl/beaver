import asyncio
import time
import inspect
import json
import uuid
from typing import (
    Any,
    Callable,
    Protocol,
    runtime_checkable,
    TYPE_CHECKING,
    Generic,
    TypeVar,
)
import weakref

from pydantic import BaseModel, Field

from .manager import AsyncBeaverBase, atomic
from .channels import AsyncBeaverChannel

if TYPE_CHECKING:
    from .core import AsyncBeaverDB

T = TypeVar("T")


class Event[T](BaseModel):
    """
    A type-safe envelope for events.

    Attributes:
        id: Unique event ID.
        event: The event name/topic.
        payload: The actual data (typed).
        timestamp: When the event was created.
    """

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    event: str
    payload: T
    timestamp: float = Field(default_factory=time.time)


class EventHandler:
    """
    Public-facing handle returned by `AsyncBeaverEvents.attach()`.
    Allows the user to close their specific callback listener.
    """

    def __init__(
        self,
        manager: "AsyncBeaverEvents",
        event: str,
        callback: Callable,
    ):
        self._manager_ref = weakref.ref(manager)
        self._event = event
        self._callback = callback
        self._closed = False

    async def off(self):
        """Removes the callback from the manager's event system."""
        if self._closed:
            return

        manager = self._manager_ref()

        if manager:
            await manager.detach(self._event, self._callback)

        self._closed = True


@runtime_checkable
class IBeaverEvents[T](Protocol):
    """Protocol exposed to the user via BeaverBridge."""

    def attach(
        self, event: str, callback: Callable[[Event[T]], Any]
    ) -> EventHandler: ...
    def detach(self, event: str, callback: Callable[[Event[T]], Any]) -> None: ...
    def emit(self, event: str, payload: T) -> None: ...


class AsyncBeaverEvents[T: BaseModel](AsyncBeaverBase[T]):
    """
    A standalone Event Bus manager.
    Implements the Observer Pattern on top of AsyncBeaverChannel.
    """

    def __init__(self, name: str, db: "AsyncBeaverDB", model: type[T] | None = None):
        super().__init__(name, db, model)
        self._callbacks: dict[str, list[Callable]] = {}
        self._listening = False
        self._listener_task: asyncio.Task | None = None

        # Internal channel for broadcasting events
        self._channel_name = f"__events_{self._name}__"
        self._channel: AsyncBeaverChannel[Event[T]] = db.channel(
            self._channel_name, model=Event[model] if model else Event
        )

    async def _ensure_listener(self):
        """Starts the background dispatch loop if not running."""
        if self._listening:
            return

        self._listening = True
        self._listener_task = asyncio.create_task(self._dispatch_loop())

    async def _dispatch_loop(self):
        """Consumes messages from the channel and executes callbacks."""
        # Subscribe to the underlying channel
        async for msg in self._channel.listen():
            # Unwrap the envelope (which is a raw dict from channel)
            event = msg.payload

            # Validate envelope structure
            event_name = event.event

            # Execute Callbacks
            for callback in self._callbacks.get(event_name, []):
                if inspect.iscoroutinefunction(callback):
                    # Run async callbacks concurrently
                    asyncio.create_task(callback(event))
                else:
                    # Run sync callbacks directly
                    callback(event)

    async def attach(self, event: str, callback: Callable[[Event[T]], Any]):
        """Attaches a callback to an event."""
        await self._ensure_listener()

        if event not in self._callbacks:
            self._callbacks[event] = []

        if callback not in self._callbacks[event]:
            self._callbacks[event].append(callback)

        return EventHandler(self, event, callback)

    async def detach(self, event: str, callback: Callable[[Event[T]], Any]):
        """Detaches a callback."""
        if event in self._callbacks:
            if callback in self._callbacks[event]:
                self._callbacks[event].remove(callback)

    @atomic
    async def emit(self, event: str, payload: T):
        """
        Emits an event.
        """
        # Publish to the underlying channel
        await self._channel.publish(Event(event=event, payload=payload))

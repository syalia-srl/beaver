import asyncio
import time
import inspect
import json
from typing import Any, Callable, Protocol, runtime_checkable, TYPE_CHECKING

from pydantic import BaseModel

from .manager import AsyncBeaverBase, atomic
from .channels import AsyncBeaverChannel

if TYPE_CHECKING:
    from .core import AsyncBeaverDB


@runtime_checkable
class IBeaverEvents[T](Protocol):
    """Protocol exposed to the user via BeaverBridge."""
    def attach(self, event: str, callback: Callable[[T], Any]) -> None: ...
    def detach(self, event: str, callback: Callable[[T], Any]) -> None: ...
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
        # We use a single channel for this event manager namespace
        self._channel_name = f"__events_{self._name}__"
        self._channel = AsyncBeaverChannel(self._channel_name, db)

    async def _ensure_listener(self):
        """Starts the background dispatch loop if not running."""
        if self._listening:
            return

        self._listening = True
        self._listener_task = asyncio.create_task(self._dispatch_loop())

    async def _dispatch_loop(self):
        """Consumes messages from the channel and executes callbacks."""
        try:
            # Subscribe to the underlying channel
            async for msg in self._channel.subscribe():
                try:
                    # Unwrap the envelope
                    # The channel gives us the raw payload (which might be a dict or T)
                    # Since we emit a dict envelope, we expect a dict here.
                    envelope = msg.payload
                    if not isinstance(envelope, dict):
                        continue

                    event_name = envelope.get("event")
                    raw_data = envelope.get("data")

                    if not event_name or event_name not in self._callbacks:
                        continue

                    # Deserialize Payload to T
                    payload = raw_data
                    if self._model and isinstance(raw_data, dict):
                        try:
                            payload = self._model.model_validate(raw_data)
                        except Exception:
                            pass # Pass dict if validation fails

                    # Execute Callbacks
                    for callback in self._callbacks[event_name]:
                        try:
                            if inspect.iscoroutinefunction(callback):
                                # Run async callbacks concurrently
                                asyncio.create_task(callback(payload))
                            else:
                                # Run sync callbacks directly (ensuring thread-safety)
                                # NOTE: if the callback is low, user must
                                # wrap it in a thread if they want
                                callback(payload)
                        except Exception:
                            pass # Log error

                except Exception:
                    pass
        except asyncio.CancelledError:
            pass

    async def attach(self, event: str, callback: Callable[[T], Any]):
        """Attaches a callback to an event."""
        await self._ensure_listener()

        if event not in self._callbacks:
            self._callbacks[event] = []

        if callback not in self._callbacks[event]:
            self._callbacks[event].append(callback)

    async def detach(self, event: str, callback: Callable[[T], Any]):
        """Detaches a callback."""
        if event in self._callbacks:
            if callback in self._callbacks[event]:
                self._callbacks[event].remove(callback)

    @atomic
    async def emit(self, event: str, payload: T):
        """
        Emits an event.
        Wraps the user payload in an envelope and publishes via the internal channel.
        """
        # Serialize inner payload first
        # We manually serialize to ensure Pydantic models are converted to JSON-safe dicts/strings
        # inside the envelope dict.
        if isinstance(payload, BaseModel):
            # model_dump(mode='json') ensures we get JSON-safe types (str, int, etc.)
            # not e.g. UUID objects which json.dumps fails on.
            data_val = payload.model_dump(mode='json')
        else:
            data_val = payload

        envelope = {
            "event": event,
            "data": data_val
        }

        # Publish to the underlying channel
        # The channel will handle serializing the envelope dict itself.
        await self._channel.publish(envelope)

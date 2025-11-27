import asyncio
import json
import time
import weakref
from typing import (
    IO,
    Any,
    Iterator,
    AsyncIterator,
    Protocol,
    runtime_checkable,
    TYPE_CHECKING,
    NamedTuple,
)

from pydantic import BaseModel

from .manager import AsyncBeaverBase, atomic, emits

if TYPE_CHECKING:
    from .core import AsyncBeaverDB


class ChannelMessage(BaseModel):
    """A message received from a channel."""

    channel: str
    payload: Any
    timestamp: float


@runtime_checkable
class IBeaverChannel[T](Protocol):
    """
    The Synchronous Protocol exposed to the user via BeaverBridge.
    """

    def publish(self, payload: T) -> None: ...
    def subscribe(self) -> Iterator[ChannelMessage]: ...
    def history(self, limit: int = 100) -> list[ChannelMessage]: ...
    def clear(self) -> None: ...
    def count(self) -> int: ...


class PubSubEngine:
    """
    A central engine that manages the background polling loop for ALL channels.
    Attached to the AsyncBeaverDB instance.
    """

    def __init__(self, db: "AsyncBeaverDB"):
        self.db = db
        self._listeners: dict[str, list[asyncio.Queue]] = {}
        self._running = False
        self._task: asyncio.Task | None = None
        self._last_poll_ts = time.time()

    async def start(self):
        """Starts the background polling loop."""
        if self._running:
            return
        self._running = True
        self._last_poll_ts = time.time()
        self._task = asyncio.create_task(self._poll_loop())

    async def stop(self):
        """Stops the background polling loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def subscribe(self, channel: str) -> asyncio.Queue:
        """Registers a new listener queue for a channel."""
        queue = asyncio.Queue()
        if channel not in self._listeners:
            self._listeners[channel] = []
        self._listeners[channel].append(queue)
        return queue

    def unsubscribe(self, channel: str, queue: asyncio.Queue):
        """Unregisters a listener."""
        if channel in self._listeners:
            if queue in self._listeners[channel]:
                self._listeners[channel].remove(queue)
            if not self._listeners[channel]:
                del self._listeners[channel]

    async def _poll_loop(self):
        """
        Periodically checks the DB for new messages and dispatches them
        to registered local queues.
        """
        while self._running:
            try:
                now = time.time()
                # 1. Fetch new messages globally
                # We use a raw execute here to avoid locking the transaction logic
                # for simple reads.
                cursor = await self.db.connection.execute(
                    """
                    SELECT timestamp, channel_name, message_payload
                    FROM __beaver_pubsub_log__
                    WHERE timestamp > ?
                    ORDER BY timestamp ASC
                    """,
                    (self._last_poll_ts,),
                )

                rows = await cursor.fetchall()
                rows = list(rows)

                if rows:
                    # Update high-water mark
                    self._last_poll_ts = rows[-1]["timestamp"]

                    # 2. Dispatch to listeners
                    for row in rows:
                        channel = row["channel_name"]
                        payload = json.loads(row["message_payload"])
                        msg = ChannelMessage(
                            channel=channel, payload=payload, timestamp=row["timestamp"]
                        )

                        # Fan-out to all queues listening on this channel
                        if channel in self._listeners:
                            for q in self._listeners[channel]:
                                q.put_nowait(msg)

                # 3. Wait before next poll
                # Adaptive sleep could be added here (e.g. sleep less if busy)
                await asyncio.sleep(0.1)

            except asyncio.CancelledError:
                break
            except Exception:
                # Log error or retry, don't crash the loop
                await asyncio.sleep(1.0)


class AsyncBeaverChannel[T: BaseModel](AsyncBeaverBase[T]):
    """
    A wrapper for a Pub/Sub channel.
    Refactored for Async-First architecture (v2.0).
    """

    async def _get_engine(self) -> PubSubEngine:
        """
        Retrieves (or creates) the shared PubSubEngine on the DB instance.
        """
        # We perform a lazy attachment to the DB instance to avoid modifying core.py
        # heavily. We store the engine on the DB instance dynamically.
        if not hasattr(self._db, "_pubsub_engine"):
            self._db._pubsub_engine = PubSubEngine(self._db)
            await self._db._pubsub_engine.start()

        return self._db._pubsub_engine

    @emits("publish", payload=lambda payload, *args, **kwargs: dict(payload=payload))
    @atomic
    async def publish(self, payload: T):
        """
        Publishes a message to the channel.
        """
        # Ensure engine is running (in case we are the first publisher)
        await self._get_engine()

        # Serialize
        data_str = self._serialize(payload)
        ts = time.time()

        # Monotonicity check (simple collision avoidance)
        # In high-throughput, we rely on the DB to serialize inserts via lock
        await self.connection.execute(
            "INSERT INTO __beaver_pubsub_log__ (timestamp, channel_name, message_payload) VALUES (?, ?, ?)",
            (ts, self._name, data_str),
        )

    async def subscribe(self) -> AsyncIterator[ChannelMessage]:
        """
        Returns an async iterator that yields new messages as they arrive.
        """
        engine = await self._get_engine()
        queue = engine.subscribe(self._name)

        try:
            while True:
                # Wait for next message from the engine
                msg = await queue.get()

                # Deserialize payload to T if possible
                # Note: The engine passes the raw dict/value.
                # We should probably deserialize it to the Model T if defined.
                if self._model and isinstance(msg.payload, dict):
                    try:
                        typed_payload = self._model.model_validate(msg.payload)
                        msg.payload = typed_payload
                    except Exception:
                        pass  # Keep as dict if validation fails

                yield msg
        finally:
            # Cleanup on break/cancel
            engine.unsubscribe(self._name, queue)

    async def history(self, limit: int = 100) -> list[ChannelMessage]:
        """
        Retrieves the last N messages from the channel history.
        """
        cursor = await self.connection.execute(
            """
            SELECT timestamp, channel_name, message_payload
            FROM __beaver_pubsub_log__
            WHERE channel_name = ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (self._name, limit),
        )

        rows = await cursor.fetchall()
        rows = list(rows)
        results = []

        # Rows are DESC, we usually want them returned chronologically
        for row in reversed(rows):
            payload = self._deserialize(row["message_payload"])
            results.append(
                ChannelMessage(
                    channel=self._name, payload=payload, timestamp=row["timestamp"]
                )
            )

        return results

    @emits("clear", payload=lambda *args, **kwargs: dict())
    @atomic
    async def clear(self):
        """Clears the history for this channel."""
        await self.connection.execute(
            "DELETE FROM __beaver_pubsub_log__ WHERE channel_name = ?", (self._name,)
        )

    async def count(self) -> int:
        """Returns the total number of messages in history."""
        cursor = await self.connection.execute(
            "SELECT COUNT(*) FROM __beaver_pubsub_log__ WHERE channel_name = ?",
            (self._name,),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

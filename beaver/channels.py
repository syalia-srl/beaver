import asyncio
import json
import sqlite3
import threading
import time
from queue import Empty, Queue
from typing import Any, AsyncIterator, Generic, Iterator, Set, Type, TypeVar

from .types import JsonSerializable

# A special message object used to signal the listener to gracefully shut down.
_SHUTDOWN_SENTINEL = object()


class AsyncSubscriber[T]:
    """A thread-safe async message receiver for a specific channel subscription."""

    def __init__(self, subscriber: "Subscriber[T]"):
        self._subscriber = subscriber

    async def __aenter__(self) -> "AsyncSubscriber[T]":
        """Registers the listener's queue with the channel to start receiving messages."""
        await asyncio.to_thread(self._subscriber.__enter__)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Unregisters the listener's queue from the channel to stop receiving messages."""
        await asyncio.to_thread(self._subscriber.__exit__, exc_type, exc_val, exc_tb)

    async def listen(self, timeout: float | None = None) -> AsyncIterator[T]:
        """
        Returns a blocking async iterator that yields messages as they arrive.
        """
        while True:
            try:
                msg = await asyncio.to_thread(self._subscriber._queue.get, timeout=timeout)
                if msg is _SHUTDOWN_SENTINEL:
                    break
                yield msg
            except Empty:
                raise TimeoutError(f"Timeout {timeout}s expired.")


class Subscriber[T]:
    """
    A thread-safe message receiver for a specific channel subscription.

    This object is designed to be used as a context manager (`with` statement).
    It holds a dedicated in-memory queue that receives messages from the
    channel's central polling thread, ensuring that a slow listener does not
    impact others.
    """

    def __init__(self, channel: "ChannelManager[T]"):
        self._channel = channel
        self._queue: Queue = Queue()

    def __enter__(self) -> "Subscriber[T]":
        """Registers the listener's queue with the channel to start receiving messages."""
        self._channel._register(self._queue)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Unregisters the listener's queue from the channel to stop receiving messages."""
        self._channel._unregister(self._queue)

    def listen(self, timeout: float | None = None) -> Iterator[T]:
        """
        Returns a blocking iterator that yields messages as they arrive.

        This method pulls messages from the listener's dedicated, thread-safe
        in-memory queue. It performs no database operations itself.

        Args:
            timeout: If provided, the iterator will raise `queue.Empty` if no message is
                     received within this many seconds.
        """
        while True:
            try:
                msg = self._queue.get(timeout=timeout)

                if msg is _SHUTDOWN_SENTINEL:
                    break

                yield msg
            except Empty:
                raise TimeoutError(f"Timeout {timeout}s expired.")

    def as_async(self) -> "AsyncSubscriber[T]":
        """Returns an async version of the subscriber."""
        return AsyncSubscriber(self)


class AsyncChannelManager[T]:
    """The central async hub for a named pub/sub channel."""

    def __init__(self, channel: "ChannelManager[T]"):
        self._channel = channel

    async def publish(self, payload: T):
        """
        Publishes a JSON-serializable message to the channel asynchronously.
        """
        await asyncio.to_thread(self._channel.publish, payload)

    def subscribe(self) -> "AsyncSubscriber[T]":
        """Creates a new async subscription, returning an AsyncSubscriber context manager."""
        return self._channel.subscribe().as_async()


class ChannelManager[T]:
    """
    The central hub for a named pub/sub channel.

    This object manages all active listeners for the channel and runs a single,
    efficient background thread to poll the database for new messages. It then
    "fans out" these messages to all subscribed listeners.
    """

    def __init__(
        self,
        name: str,
        conn: sqlite3.Connection,
        db_path: str,
        poll_interval: float = 0.1,
        model: Type[T] | None = None,
    ):
        self._name = name
        self._conn = conn
        self._db_path = db_path
        self._poll_interval = poll_interval
        self._model = model
        self._listeners: Set[Queue] = set()
        self._lock = threading.Lock()
        self._polling_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def _serialize(self, value: T) -> str:
        """Serializes the given value to a JSON string."""
        if isinstance(value, JsonSerializable):
            return value.model_dump_json()

        return json.dumps(value)

    def _deserialize(self, value: str) -> T:
        """Deserializes a JSON string into the specified model or a generic object."""
        if self._model:
            return self._model.model_validate_json(value)

        return json.loads(value)

    def _register(self, queue: Queue):
        """Adds a listener's queue and starts the poller if it's the first one."""

        with self._lock:
            self._listeners.add(queue)
            # If the polling thread isn't running, start it.
            if self._polling_thread is None or not self._polling_thread.is_alive():
                self._start_polling()

    def _unregister(self, queue: Queue):
        """Removes a listener's queue and stops the poller if it's the last one."""

        with self._lock:
            self._listeners.discard(queue)
            # If there are no more listeners, stop the polling thread to save resources.
            if not self._listeners:
                self._stop_polling()

    def _start_polling(self):
        """Starts the background polling thread."""
        self._stop_event.clear()
        self._polling_thread = threading.Thread(target=self._polling_loop, daemon=True)
        self._polling_thread.start()

    def _stop_polling(self):
        """Signals the background polling thread to stop."""
        if self._polling_thread and self._polling_thread.is_alive():
            self._stop_event.set()
            self._polling_thread.join()
            self._polling_thread = None

    def close(self):
        """Reliable close this channel and removes listeners."""
        self._stop_polling()

        with self._lock:
            for listener in self._listeners:
                listener.put(_SHUTDOWN_SENTINEL)

        self._listeners.clear()

    def _polling_loop(self):
        """
        The main loop for the background thread.

        This function polls the database for new messages and fans them out
        to all registered listener queues.
        """
        # A separate SQLite connection is required for each thread.
        thread_conn = sqlite3.connect(self._db_path, check_same_thread=False)
        thread_conn.row_factory = sqlite3.Row

        # The poller starts listening for messages from this moment forward.
        last_seen_timestamp = time.time()

        while not self._stop_event.is_set():
            cursor = thread_conn.cursor()
            cursor.execute(
                "SELECT timestamp, message_payload FROM beaver_pubsub_log WHERE channel_name = ? AND timestamp > ? ORDER BY timestamp ASC",
                (self._name, last_seen_timestamp),
            )
            messages = cursor.fetchall()
            cursor.close()

            if messages:
                # Update the timestamp to the last message we've seen.
                last_seen_timestamp = messages[-1]["timestamp"]

                # The "fan-out": Push messages to all active listener queues.
                # This block is locked to prevent modification of the listeners set
                # while we are iterating over it.
                with self._lock:
                    for queue in self._listeners:
                        for row in messages:
                            queue.put(self._deserialize(row["message_payload"]))

            # Wait for the poll interval before checking for new messages again.
            time.sleep(self._poll_interval)

        thread_conn.close()

    def subscribe(self) -> Subscriber[T]:
        """Creates a new subscription, returning a Listener context manager."""
        return Subscriber(self)

    def publish(self, payload: T):
        """
        Publishes a JSON-serializable message to the channel.

        This is a synchronous operation that performs a fast, atomic INSERT
        into the database's pub/sub log.
        """
        try:
            json_payload = self._serialize(payload)
        except TypeError as e:
            raise TypeError("Message payload must be JSON-serializable.") from e

        with self._conn:
            self._conn.execute(
                "INSERT INTO beaver_pubsub_log (timestamp, channel_name, message_payload) VALUES (?, ?, ?)",
                (time.time(), self._name, json_payload),
            )

    def as_async(self) -> "AsyncChannelManager[T]":
        """Returns an async version of the channel manager."""
        return AsyncChannelManager(self)

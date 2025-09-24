import asyncio
import collections
import json
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from queue import Empty, Queue
from typing import Any, AsyncIterator, Callable, Iterator, Type, TypeVar

from .types import JsonSerializable


# A special message object used to signal the iterator to gracefully shut down.
_SHUTDOWN_SENTINEL = object()


class LiveIterator[T,R]:
    """
    A thread-safe, blocking iterator that yields aggregated results from a
    rolling window of log data.
    """

    def __init__(
        self,
        db_path: str,
        log_name: str,
        window: timedelta,
        period: timedelta,
        aggregator: Callable[[list[T]], R],
        deserializer: Callable[[str], T],
    ):
        self._db_path = db_path
        self._log_name = log_name
        self._window_duration_seconds = window.total_seconds()
        self._sampling_period_seconds = period.total_seconds()
        self._aggregator = aggregator
        self._deserializer = deserializer
        self._queue: Queue = Queue()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def _polling_loop(self):
        """The main loop for the background thread that queries and aggregates data."""
        # Each thread needs its own database connection.
        thread_conn = sqlite3.connect(self._db_path, check_same_thread=False)
        thread_conn.row_factory = sqlite3.Row

        window_deque: collections.deque[tuple[float, T]] = collections.deque()
        last_seen_timestamp = 0.0

        # --- Initial window population ---
        now = datetime.now(timezone.utc).timestamp()
        start_time = now - self._window_duration_seconds
        cursor = thread_conn.cursor()
        cursor.execute(
            "SELECT timestamp, data FROM beaver_logs WHERE log_name = ? AND timestamp >= ? ORDER BY timestamp ASC",
            (self._log_name, start_time),
        )
        for row in cursor:
            ts, data_str = row
            window_deque.append((ts, self._deserializer(data_str)))
            last_seen_timestamp = max(last_seen_timestamp, ts)

        # Yield the first result
        try:
            initial_result = self._aggregator([item[1] for item in window_deque])
            self._queue.put(initial_result)
        except Exception as e:
            # Propagate aggregator errors to the main thread
            self._queue.put(e)

        # --- Continuous polling loop ---
        while not self._stop_event.is_set():
            time.sleep(self._sampling_period_seconds)

            # Fetch only new data since the last check
            cursor.execute(
                "SELECT timestamp, data FROM beaver_logs WHERE log_name = ? AND timestamp > ? ORDER BY timestamp ASC",
                (self._log_name, last_seen_timestamp),
            )
            for row in cursor:
                ts, data_str = row
                window_deque.append((ts, self._deserializer(data_str)))
                last_seen_timestamp = max(last_seen_timestamp, ts)

            # Evict old data from the left of the deque
            now = datetime.now(timezone.utc).timestamp()
            eviction_time = now - self._window_duration_seconds
            while window_deque and window_deque[0][0] < eviction_time:
                window_deque.popleft()

            # Run aggregator and yield the new result
            try:
                new_result = self._aggregator([item[1] for item in window_deque])
                self._queue.put(new_result)
            except Exception as e:
                self._queue.put(e)

        thread_conn.close()

    def __iter__(self) -> "LiveIterator[T,R]":
        self._thread = threading.Thread(target=self._polling_loop, daemon=True)
        self._thread.start()
        return self

    def __next__(self) -> R:
        result = self._queue.get()
        if result is _SHUTDOWN_SENTINEL:
            raise StopIteration
        if isinstance(result, Exception):
            # If the background thread put an exception in the queue, re-raise it
            raise result
        return result

    def close(self):
        """Stops the background polling thread."""
        self._stop_event.set()
        self._queue.put(_SHUTDOWN_SENTINEL)
        if self._thread:
            self._thread.join()


class AsyncLiveIterator[T,R]:
    """An async wrapper for the LiveIterator."""

    def __init__(self, sync_iterator: LiveIterator[T,R]):
        self._sync_iterator = sync_iterator

    async def __anext__(self) -> R:
        try:
            return await asyncio.to_thread(self._sync_iterator.__next__)
        except StopIteration:
            raise StopAsyncIteration

    def __aiter__(self) -> "AsyncLiveIterator[T,R]":
        # The synchronous iterator's __iter__ method starts the thread.
        # This is non-blocking, so it's safe to call directly.
        self._sync_iterator.__iter__()
        return self

    def close(self):
        self._sync_iterator.close()


class AsyncLogManager[T]:
    """An async-compatible wrapper for the LogManager."""

    def __init__(self, sync_manager: "LogManager[T]"):
        self._sync_manager = sync_manager

    async def log(self, data: T, timestamp: datetime | None = None) -> None:
        """Asynchronously adds a new entry to the log."""
        await asyncio.to_thread(self._sync_manager.log, data, timestamp)

    async def range(self, start: datetime, end: datetime) -> list[T]:
        """Asynchronously retrieves all log entries within a specific time window."""
        return await asyncio.to_thread(self._sync_manager.range, start, end)

    def live[R](
        self,
        window: timedelta,
        period: timedelta,
        aggregator: Callable[[list[T]], R],
    ) -> AsyncIterator[R]:
        """Returns an async, infinite iterator for real-time log analysis."""
        sync_iterator = self._sync_manager.live(
            window, period, aggregator
        )
        return AsyncLiveIterator(sync_iterator)


class LogManager[T]:
    """
    A wrapper for interacting with a named, time-indexed log, providing
    type-safe and async-compatible methods.
    """

    def __init__(
        self,
        name: str,
        conn: sqlite3.Connection,
        db_path: str,
        model: Type[T] | None = None,
    ):
        self._name = name
        self._conn = conn
        self._db_path = db_path
        self._model = model

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

    def log(self, data: T, timestamp: datetime | None = None) -> None:
        """
        Adds a new entry to the log.

        Args:
            data: The JSON-serializable data to store. If a model is used, this
                  should be an instance of that model.
            timestamp: A timezone-naive datetime object. If not provided,
                       `datetime.now()` is used.
        """
        ts = timestamp or datetime.now(timezone.utc)
        ts_float = ts.timestamp()

        with self._conn:
            self._conn.execute(
                "INSERT INTO beaver_logs (log_name, timestamp, data) VALUES (?, ?, ?)",
                (self._name, ts_float, self._serialize(data)),
            )

    def range(self, start: datetime, end: datetime) -> list[T]:
        """
        Retrieves all log entries within a specific time window.

        Args:
            start: The start of the time range (inclusive).
            end: The end of the time range (inclusive).

        Returns:
            A list of log entries, deserialized into the specified model if provided.
        """
        start_ts = start.timestamp()
        end_ts = end.timestamp()

        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT data FROM beaver_logs WHERE log_name = ? AND timestamp BETWEEN ? AND ? ORDER BY timestamp ASC",
            (self._name, start_ts, end_ts),
        )
        return [self._deserialize(row["data"]) for row in cursor.fetchall()]

    def live[R](
        self,
        window: timedelta,
        period: timedelta,
        aggregator: Callable[[list[T]], R],
    ) -> Iterator[R]:
        """
        Returns a blocking, infinite iterator for real-time log analysis.

        This maintains a sliding window of log entries and yields the result
        of an aggregator function at specified intervals.

        Args:
            window: The duration of the sliding window (e.g., `timedelta(minutes=5)`).
            period: The interval at which to update and yield a new result
                             (e.g., `timedelta(seconds=10)`).
            aggregator: A function that takes a list of log entries (the window) and
                        returns a single, aggregated result.

        Returns:
            An iterator that yields the results of the aggregator.
        """
        return LiveIterator(
            db_path=self._db_path,
            log_name=self._name,
            window=window,
            period=period,
            aggregator=aggregator,
            deserializer=self._deserialize,
        )

    def as_async(self) -> AsyncLogManager[T]:
        """Returns an async-compatible version of the log manager."""
        return AsyncLogManager(self)

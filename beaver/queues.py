import asyncio
from datetime import datetime, timezone
import json
import sqlite3
import time
from typing import IO, Any, Iterator, Literal, NamedTuple, Type, overload, Optional
from .types import JsonSerializable, IDatabase
from .locks import LockManager
from .manager import ManagerBase, synced


class QueueItem[T](NamedTuple):
    """A data class representing a single item retrieved from the queue."""

    priority: float
    timestamp: float
    data: T


class AsyncQueueManager[T: JsonSerializable]:
    """An async wrapper for the producer-consumer priority queue."""

    def __init__(self, queue: "QueueManager[T]"):
        self._queue = queue

    async def put(self, data: T, priority: float):
        """Asynchronously adds an item to the queue with a specific priority."""
        await asyncio.to_thread(self._queue.put, data, priority)

    async def peek(self) -> QueueItem[T] | None:
        """
        Asynchronously returns the first item without removing it, if any, otherwise returns None.
        """
        return await asyncio.to_thread(self._queue.peek)

    @overload
    async def get(
        self, block: Literal[True] = True, timeout: float | None = None
    ) -> QueueItem[T]: ...
    @overload
    async def get(self, block: Literal[False]) -> QueueItem[T]: ...

    async def get(
        self, block: bool = True, timeout: float | None = None
    ) -> QueueItem[T]:
        """
        Asynchronously and atomically retrieves the highest-priority item.
        This method will run the synchronous blocking logic in a separate thread.
        """
        return await asyncio.to_thread(self._queue.get, block=block, timeout=timeout)


class QueueManager[T: JsonSerializable](ManagerBase[T]):
    """
    A wrapper providing a Pythonic interface to a persistent, multi-process
    producer-consumer priority queue.
    """

    @synced
    def put(self, data: T, priority: float):
        """
        Adds an item to the queue with a specific priority.

        Args:
            data: The JSON-serializable data to store.
            priority: The priority of the item (lower numbers are higher priority).
        """
        self.connection.execute(
            "INSERT INTO beaver_priority_queues (queue_name, priority, timestamp, data) VALUES (?, ?, ?, ?)",
            (self._name, priority, time.time(), self._serialize(data)),
        )

    @synced
    def _get_item_atomically(self, pop: bool = True) -> QueueItem[T] | None:
        """
        Performs a single, atomic attempt to retrieve and remove the
        highest-priority item from the queue. Returns None if the queue is empty.
        """
        with self.connection:
            cursor = self.connection.cursor()
            cursor.execute(
                """
                SELECT rowid, priority, timestamp, data
                FROM beaver_priority_queues
                WHERE queue_name = ?
                ORDER BY priority ASC, timestamp ASC
                LIMIT 1
                """,
                (self._name,),
            )
            result = cursor.fetchone()

            if result is None:
                return None

            rowid, priority, timestamp, data = result

            if pop:
                self.connection.execute(
                    "DELETE FROM beaver_priority_queues WHERE rowid = ?", (rowid,)
                )

        return QueueItem(
            priority=priority, timestamp=timestamp, data=self._deserialize(data)
        )

    def peek(self) -> QueueItem[T] | None:
        """
        Retrieves the first item of the queue.
        If the queue is empy, returns None.
        """
        return self._get_item_atomically(pop=False)

    @overload
    def get(
        self, block: Literal[True] = True, timeout: float | None = None
    ) -> QueueItem[T]: ...
    @overload
    def get(self, block: Literal[False]) -> QueueItem[T]: ...

    def get(self, block: bool = True, timeout: float | None = None) -> QueueItem[T]:
        """
        Atomically retrieves and removes the highest-priority item from the queue.

        This method is designed for producer-consumer patterns and can block
        until an item becomes available.

        Args:
            block: If True (default), the method will wait until an item is available.
            timeout: If `block` is True, this specifies the maximum number of seconds
                     to wait. If the timeout is reached, `TimeoutError` is raised.

        Returns:
            A `QueueItem` containing the retrieved data.

        Raises:
            IndexError: If `block` is False and the queue is empty.
            TimeoutError: If `block` is True and the timeout expires.
        """
        if not block:
            item = self._get_item_atomically()
            if item is None:
                raise IndexError("get from an empty queue.")
            return item

        start_time = time.time()
        while True:
            item = self._get_item_atomically()
            if item is not None:
                return item

            if timeout is not None and (time.time() - start_time) > timeout:
                raise TimeoutError("Timeout expired while waiting for an item.")

            # Sleep for a short interval to avoid busy-waiting and consuming CPU.
            time.sleep(0.1)

    def as_async(self) -> "AsyncQueueManager[T]":
        """Returns an async version of the queue manager."""
        return AsyncQueueManager(self)

    def __len__(self) -> int:
        """Returns the current number of items in the queue."""
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM beaver_priority_queues WHERE queue_name = ?",
            (self._name,),
        )
        count = cursor.fetchone()[0]
        cursor.close()
        return count

    def __bool__(self) -> bool:
        """Returns True if the queue is not empty."""
        return len(self) > 0

    def __repr__(self) -> str:
        return f"QueueManager(name='{self._name}')"

    def __iter__(self) -> Iterator[QueueItem[T]]:
        """
        Returns an iterator over all items in the queue, in priority order,
        without removing them.

        Yields:
            QueueItem: The next item in the queue (priority, timestamp, data).
        """
        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT priority, timestamp, data
            FROM beaver_priority_queues
            WHERE queue_name = ?
            ORDER BY priority ASC, timestamp ASC
            """,
            (self._name,),
        )
        try:
            for row in cursor:
                yield QueueItem(
                    priority=row["priority"],
                    timestamp=row["timestamp"],
                    data=self._deserialize(row["data"]),
                )
        finally:
            cursor.close()

    def _get_dump_object(self) -> dict:
        """Builds the JSON-compatible dump object."""

        items_list = []
        # Use the new __iter__ method
        for item in self:
            data = item.data

            # Handle model instances
            if self._model and isinstance(data, JsonSerializable):
                data = json.loads(data.model_dump_json())

            items_list.append(
                {"priority": item.priority, "timestamp": item.timestamp, "data": data}
            )

        metadata = {
            "type": "Queue",
            "name": self._name,
            "count": len(items_list),
            "dump_date": datetime.now(timezone.utc).isoformat(),
        }

        return {"metadata": metadata, "items": items_list}

    @overload
    def dump(self) -> dict:
        pass

    @overload
    def dump(self, fp: IO[str]) -> None:
        pass

    def dump(self, fp: IO[str] | None = None) -> dict | None:
        """
        Dumps the entire contents of the queue to a JSON-compatible
        Python object or a file-like object.

        Args:
            fp: A file-like object opened in text mode (e.g., with 'w').
                If provided, the JSON dump will be written to this file.
                If None (default), the dump will be returned as a dictionary.

        Returns:
            A dictionary containing the dump if fp is None.
            None if fp is provided.
        """
        dump_object = self._get_dump_object()

        if fp:
            json.dump(dump_object, fp, indent=2)
            return None

        return dump_object

    @synced
    def clear(self):
        """
        Atomically removes all items from this queue.
        """
        self.connection.execute(
            "DELETE FROM beaver_priority_queues WHERE queue_name = ?",
            (self._name,),
        )

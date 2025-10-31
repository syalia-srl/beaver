import asyncio
import json
import sqlite3
import time
from typing import Any, Literal, NamedTuple, Type, overload, Optional
from .types import JsonSerializable, IDatabase
from .locks import LockManager

class QueueItem[T](NamedTuple):
    """A data class representing a single item retrieved from the queue."""

    priority: float
    timestamp: float
    data: T


class AsyncQueueManager[T]:
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
    async def get(self, block: Literal[True] = True, timeout: float | None = None) -> QueueItem[T]: ...
    @overload
    async def get(self, block: Literal[False]) -> QueueItem[T]: ...

    async def get(self, block: bool = True, timeout: float | None = None) -> QueueItem[T]:
        """
        Asynchronously and atomically retrieves the highest-priority item.
        This method will run the synchronous blocking logic in a separate thread.
        """
        return await asyncio.to_thread(self._queue.get, block=block, timeout=timeout)


class QueueManager[T]:
    """
    A wrapper providing a Pythonic interface to a persistent, multi-process
    producer-consumer priority queue.
    """

    def __init__(self, name: str, db: IDatabase, model: Type[T] | None = None):
        self._name = name
        self._db = db
        self._model = model
        lock_name = f"__lock__queue__{name}"
        self._lock = LockManager(db, lock_name)

    def _serialize(self, value: T) -> str:
        """Serializes the given value to a JSON string."""
        if isinstance(value, JsonSerializable):
            return value.model_dump_json()

        return json.dumps(value)

    def _deserialize(self, value: str) -> T:
        """Deserializes a JSON string into the specified model or a generic object."""
        if self._model is not None:
            return self._model.model_validate_json(value) # type: ignore

        return json.loads(value)

    def put(self, data: T, priority: float):
        """
        Adds an item to the queue with a specific priority.

        Args:
            data: The JSON-serializable data to store.
            priority: The priority of the item (lower numbers are higher priority).
        """
        with self._db.connection:
            self._db.connection.execute(
                "INSERT INTO beaver_priority_queues (queue_name, priority, timestamp, data) VALUES (?, ?, ?, ?)",
                (self._name, priority, time.time(), self._serialize(data)),
            )

    def _get_item_atomically(self, pop:bool=True) -> QueueItem[T] | None:
        """
        Performs a single, atomic attempt to retrieve and remove the
        highest-priority item from the queue. Returns None if the queue is empty.
        """
        with self._db.connection:
            cursor = self._db.connection.cursor()
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
                self._db.connection.execute("DELETE FROM beaver_priority_queues WHERE rowid = ?", (rowid,))

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
    def get(self, block: Literal[True] = True, timeout: float | None = None) -> QueueItem[T]: ...
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
        cursor = self._db.connection.cursor()
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

    def acquire(
        self,
        timeout: Optional[float] = None,
        lock_ttl: Optional[float] = None,
        poll_interval: Optional[float] = None,
    ) -> "QueueManager[T]":
        """
        Acquires an inter-process lock on this queue, blocking until acquired.
        This ensures that a sequence of operations (e.g., batch-getting tasks)
        is performed atomically without interruption from other processes.

        Parameters override the default settings of the underlying LockManager.
        """
        self._lock.acquire(
            timeout=timeout,
            lock_ttl=lock_ttl,
            poll_interval=poll_interval
        )
        return self

    def release(self):
        """
        Releases the inter-process lock on this queue.
        """
        self._lock.release()

    def __enter__(self) -> "QueueManager[T]":
        """Acquires the lock upon entering a 'with' statement."""
        return self.acquire()

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Releases the lock when exiting a 'with' statement."""
        self.release()

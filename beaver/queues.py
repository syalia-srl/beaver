import json
import sqlite3
import time
from typing import Any, Literal, NamedTuple, Type, overload

from .types import JsonSerializable


class QueueItem[T](NamedTuple):
    """A data class representing a single item retrieved from the queue."""

    priority: float
    timestamp: float
    data: T


class QueueManager[T]:
    """A wrapper providing a Pythonic interface to a persistent priority queue."""

    def __init__(self, name: str, conn: sqlite3.Connection, model: Type[T] | None = None):
        self._name = name
        self._conn = conn
        self._model = model

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
        with self._conn:
            self._conn.execute(
                "INSERT INTO beaver_priority_queues (queue_name, priority, timestamp, data) VALUES (?, ?, ?, ?)",
                (self._name, priority, time.time(), self._serialize(data)),
            )

    @overload
    def get(self, safe:Literal[True]) -> QueueItem[T] | None: ...
    @overload
    def get(self) -> QueueItem[T]: ...

    def get(self, safe:bool=False) -> QueueItem[T] | None:
        """
        Atomically retrieves and removes the highest-priority item from the queue.
        If the queue is empty, returns None if safe is True, otherwise (the default) raises IndexError.
        """
        with self._conn:
            cursor = self._conn.cursor()
            # The compound index on (queue_name, priority, timestamp) makes this query efficient.
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
                if safe:
                    return None
                else:
                    raise IndexError("No item available.")

            rowid, priority, timestamp, data = result
            # Delete the retrieved item to ensure it's processed only once.
            cursor.execute("DELETE FROM beaver_priority_queues WHERE rowid = ?", (rowid,))

            return QueueItem(
                priority=priority, timestamp=timestamp, data=self._deserialize(data)
            )

    def __len__(self) -> int:
        """Returns the current number of items in the queue."""
        cursor = self._conn.cursor()
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

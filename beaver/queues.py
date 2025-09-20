import json
import sqlite3
import time
from typing import Any, NamedTuple


class QueueItem(NamedTuple):
    """A data class representing a single item retrieved from the queue."""

    priority: float
    timestamp: float
    data: Any


class QueueManager:
    """A wrapper providing a Pythonic interface to a persistent priority queue."""

    def __init__(self, name: str, conn: sqlite3.Connection):
        self._name = name
        self._conn = conn

    def put(self, data: Any, priority: float):
        """
        Adds an item to the queue with a specific priority.

        Args:
            data: The JSON-serializable data to store.
            priority: The priority of the item (lower numbers are higher priority).
        """
        with self._conn:
            self._conn.execute(
                "INSERT INTO beaver_priority_queues (queue_name, priority, timestamp, data) VALUES (?, ?, ?, ?)",
                (self._name, priority, time.time(), json.dumps(data)),
            )

    def get(self) -> QueueItem:
        """
        Atomically retrieves and removes the highest-priority item from the queue.

        Returns:
            A QueueItem containing the data and its metadata.

        Raises IndexError if queue is empty.
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
                raise IndexError("Queue is empty")

            rowid, priority, timestamp, data = result
            # Delete the retrieved item to ensure it's processed only once.
            cursor.execute("DELETE FROM beaver_priority_queues WHERE rowid = ?", (rowid,))

            return QueueItem(
                priority=priority, timestamp=timestamp, data=json.loads(data)
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

    def __nonzero__(self) -> bool:
        """Returns True if the queue is not empty."""
        return len(self) > 0

    def __repr__(self) -> str:
        return f"QueueManager(name='{self._name}')"

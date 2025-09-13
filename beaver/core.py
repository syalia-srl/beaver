import asyncio
import json
import sqlite3
import time
from typing import Any, AsyncIterator

# --- SQL Schema ---
# These statements are executed once to set up the database.

PUBSUB_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS _beaver_pubsub_log (
    timestamp REAL PRIMARY KEY,
    channel_name TEXT NOT NULL,
    message_payload TEXT NOT NULL
);
"""

PUBSUB_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS _beaver_idx_pubsub_channel_timestamp
ON _beaver_pubsub_log (channel_name, timestamp);
"""


class Subscriber(AsyncIterator):
    """
    A stateful, async context manager for receiving messages from a channel.

    This object is returned by `BeaverDB.subscribe()` and is designed to
    be used with `async with` and `async for`.
    """
    def __init__(self, db_path: str, channel_name: str, poll_interval: float = 0.1):
        self._db_path = db_path
        self._channel = channel_name
        self._poll_interval = poll_interval
        self._queue = asyncio.Queue()
        self._last_seen_timestamp = time.time()
        self._polling_task = None

    async def _poll_for_messages(self):
        """A background task that polls SQLite for new messages."""
        while True:
            try:
                # Run the synchronous DB query in a thread to avoid blocking asyncio
                new_messages = await asyncio.to_thread(
                    self._fetch_new_messages_from_db
                )

                if new_messages:
                    for timestamp, payload_str in new_messages:
                        payload = json.loads(payload_str)
                        await self._queue.put(payload)
                        self._last_seen_timestamp = timestamp

                await asyncio.sleep(self._poll_interval)
            except asyncio.CancelledError:
                # Gracefully exit when the task is cancelled
                break
            except Exception as e:
                # In a real app, you'd add more robust logging/error handling
                print(f"ERROR: Pub/sub polling task failed: {e}")
                await asyncio.sleep(self._poll_interval * 5) # Back off on error

    def _fetch_new_messages_from_db(self) -> list[tuple[float, str]]:
        """The actual synchronous database query using sqlite3."""
        # Each call in a separate thread gets its own connection object.
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT timestamp, message_payload FROM _beaver_pubsub_log "
                "WHERE channel_name = ? AND timestamp > ? "
                "ORDER BY timestamp ASC",
                (self._channel, self._last_seen_timestamp)
            )
            return cursor.fetchall()

    async def __aenter__(self):
        """Starts the background task when entering an 'async with' block."""
        if not self._polling_task:
            self._polling_task = asyncio.create_task(self._poll_for_messages())
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Stops the background task when exiting the 'async with' block."""
        if self._polling_task:
            self._polling_task.cancel()
            await asyncio.gather(self._polling_task, return_exceptions=True)

    def __aiter__(self):
        return self

    async def __anext__(self) -> Any:
        """Allows 'async for' to pull messages from the internal queue."""
        return await self._queue.get()


class BeaverDB:
    """
    A single-file, multi-modal database for Python.

    Currently provides asynchronous pub/sub functionality using the standard
    sqlite3 library.
    """
    def __init__(self, db_path: str = "beaver.db"):
        """
        Initializes the database.

        Args:
            db_path: The path to the SQLite database file.
        """
        self.db_path = db_path
        self._setup_database()

    def _setup_database(self):
        """Creates the necessary tables and indices if they don't exist."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(PUBSUB_TABLE_SQL)
            cursor.execute(PUBSUB_INDEX_SQL)
            conn.commit()

    async def publish(self, channel_name: str, payload: Any):
        """
        Publishes a JSON-serializable message to a channel.

        Args:
            channel_name: The name of the channel.
            payload: A JSON-serializable Python object (e.g., dict, list).
        """
        if not isinstance(channel_name, str) or not channel_name:
            raise ValueError("Channel name must be a non-empty string.")

        try:
            json_payload = json.dumps(payload)
        except TypeError as e:
            raise TypeError("Message payload must be JSON-serializable.") from e

        # Run the blocking DB write in a thread to keep this method non-blocking
        await asyncio.to_thread(
            self._write_publish_to_db, channel_name, json_payload
        )

    def _write_publish_to_db(self, channel_name: str, json_payload: str):
        """The synchronous part of the publish operation using sqlite3."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO _beaver_pubsub_log (timestamp, channel_name, message_payload) "
                "VALUES (?, ?, ?)",
                (time.time(), channel_name, json_payload)
            )
            conn.commit()

    def subscribe(self, channel_name: str) -> Subscriber:
        """
        Subscribes to a channel.

        Returns a 'Subscriber' object that can be used in an 'async with'
        block and `async for` loop to receive messages.

        Args:
            channel_name: The name of the channel to subscribe to.
        """
        return Subscriber(self.db_path, channel_name)

import asyncio
import json
import sqlite3
import time
from typing import Any, AsyncIterator


class BeaverDB:
    """
    An embedded, multi-modal database in a single SQLite file.
    Currently supports async pub/sub and a synchronous key-value store.
    """

    def __init__(self, db_path: str):
        """
        Initializes the database connection and creates necessary tables.

        Args:
            db_path: The path to the SQLite database file.
        """
        self._db_path = db_path
        # Enable WAL mode for better concurrency between readers and writers
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.row_factory = sqlite3.Row
        self._create_pubsub_table()
        self._create_kv_table()

    def _create_pubsub_table(self):
        """Creates the pub/sub log table if it doesn't exist."""
        with self._conn:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS beaver_pubsub_log (
                    timestamp REAL PRIMARY KEY,
                    channel_name TEXT NOT NULL,
                    message_payload TEXT NOT NULL
                )
            """)
            self._conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_pubsub_channel_timestamp
                ON beaver_pubsub_log (channel_name, timestamp)
            """)

    def _create_kv_table(self):
        """Creates the key-value store table if it doesn't exist."""
        with self._conn:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS _beaver_kv_store (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)

    def close(self):
        """Closes the database connection."""
        if self._conn:
            self._conn.close()

    # --- Key-Value Store Methods ---

    def set(self, key: str, value: Any):
        """
        Stores a JSON-serializable value for a given key.
        This operation is synchronous.

        Args:
            key: The unique string identifier for the value.
            value: A JSON-serializable Python object (dict, list, str, int, etc.).

        Raises:
            TypeError: If the key is not a string or the value is not JSON-serializable.
        """
        if not isinstance(key, str):
            raise TypeError("Key must be a string.")

        try:
            json_value = json.dumps(value)
        except TypeError as e:
            raise TypeError("Value must be JSON-serializable.") from e

        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO _beaver_kv_store (key, value) VALUES (?, ?)",
                (key, json_value)
            )

    def get(self, key: str) -> Any:
        """
        Retrieves a value for a given key.
        This operation is synchronous.

        Args:
            key: The string identifier for the value.

        Returns:
            The deserialized Python object, or None if the key is not found.

        Raises:
            TypeError: If the key is not a string.
        """
        if not isinstance(key, str):
            raise TypeError("Key must be a string.")

        cursor = self._conn.cursor()
        cursor.execute("SELECT value FROM _beaver_kv_store WHERE key = ?", (key,))
        result = cursor.fetchone()
        cursor.close()

        if result:
            return json.loads(result['value'])
        return None

    # --- Asynchronous Pub/Sub Methods ---

    async def publish(self, channel_name: str, payload: Any):
        """
        Publishes a JSON-serializable message to a channel.
        This operation is asynchronous.
        """
        if not isinstance(channel_name, str) or not channel_name:
            raise ValueError("Channel name must be a non-empty string.")
        try:
            json_payload = json.dumps(payload)
        except TypeError as e:
            raise TypeError("Message payload must be JSON-serializable.") from e

        await asyncio.to_thread(
            self._write_publish_to_db, channel_name, json_payload
        )

    def _write_publish_to_db(self, channel_name, json_payload):
        """The synchronous part of the publish operation."""
        with self._conn:
            self._conn.execute(
                "INSERT INTO beaver_pubsub_log (timestamp, channel_name, message_payload) VALUES (?, ?, ?)",
                (time.time(), channel_name, json_payload)
            )

    def subscribe(self, channel_name: str) -> "Subscriber":
        """
        Subscribes to a channel, returning an async iterator.
        """
        return Subscriber(self._conn, channel_name)


class Subscriber(AsyncIterator):
    """
    An async iterator that polls a channel for new messages.
    Designed to be used with 'async with'.
    """

    def __init__(self, conn: sqlite3.Connection, channel_name: str, poll_interval: float = 0.1):
        self._conn = conn
        self._channel = channel_name
        self._poll_interval = poll_interval
        self._queue = asyncio.Queue()
        self._last_seen_timestamp = time.time()
        self._polling_task = None

    async def _poll_for_messages(self):
        """Background task that polls the database for new messages."""
        while True:
            try:
                new_messages = await asyncio.to_thread(
                    self._fetch_new_messages_from_db
                )
                if new_messages:
                    for msg in new_messages:
                        payload = json.loads(msg["message_payload"])
                        await self._queue.put(payload)
                        self._last_seen_timestamp = msg["timestamp"]
                await asyncio.sleep(self._poll_interval)
            except asyncio.CancelledError:
                break
            except Exception:
                # In a real app, add more robust error logging
                await asyncio.sleep(self._poll_interval * 5)

    def _fetch_new_messages_from_db(self) -> list:
        """The actual synchronous database query."""
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT timestamp, message_payload FROM beaver_pubsub_log WHERE channel_name = ? AND timestamp > ? ORDER BY timestamp ASC",
            (self._channel, self._last_seen_timestamp)
        )
        results = cursor.fetchall()
        cursor.close()
        return results

    async def __aenter__(self):
        """Starts the background task."""
        self._polling_task = asyncio.create_task(self._poll_for_messages())
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Stops the background task."""
        if self._polling_task:
            self._polling_task.cancel()
            await asyncio.gather(self._polling_task, return_exceptions=True)

    def __aiter__(self):
        return self

    async def __anext__(self) -> Any:
        """Allows 'async for' to pull messages from the internal queue."""
        return await self._queue.get()

import asyncio
import json
import sqlite3
import time
from typing import Any, AsyncIterator, Union


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
        self._create_list_table()

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

    def _create_list_table(self):
        """Creates the lists table if it doesn't exist."""
        with self._conn:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS beaver_lists (
                    list_name TEXT NOT NULL,
                    item_order REAL NOT NULL,
                    item_value TEXT NOT NULL,
                    PRIMARY KEY (list_name, item_order)
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

    # --- List Methods ---

    def list(self, name: str) -> "ListWrapper":
        """
        Returns a wrapper object for interacting with a specific list.

        Args:
            name: The name of the list.

        Returns:
            A ListWrapper instance bound to the given list name.
        """
        if not isinstance(name, str) or not name:
            raise TypeError("List name must be a non-empty string.")
        return ListWrapper(name, self._conn)

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


class ListWrapper:
    """A wrapper providing a Pythonic interface to a list in the database."""

    def __init__(self, name: str, conn: sqlite3.Connection):
        self._name = name
        self._conn = conn

    def __len__(self) -> int:
        """Returns the number of items in the list (e.g., `len(my_list)`)."""
        cursor = self._conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM beaver_lists WHERE list_name = ?", (self._name,))
        count = cursor.fetchone()[0]
        cursor.close()
        return count

    def __getitem__(self, key: Union[int, slice]) -> Any:
        """
        Retrieves an item or slice from the list (e.g., `my_list[0]`, `my_list[1:3]`).
        """
        if isinstance(key, slice):
            start, stop, step = key.indices(len(self))
            if step != 1:
                raise ValueError("Slicing with a step is not supported.")

            limit = stop - start
            if limit <= 0:
                return []

            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT item_value FROM beaver_lists WHERE list_name = ? ORDER BY item_order ASC LIMIT ? OFFSET ?",
                (self._name, limit, start)
            )
            results = [json.loads(row['item_value']) for row in cursor.fetchall()]
            cursor.close()
            return results

        elif isinstance(key, int):
            list_len = len(self)
            if key < -list_len or key >= list_len:
                raise IndexError("List index out of range.")

            offset = key if key >= 0 else list_len + key

            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT item_value FROM beaver_lists WHERE list_name = ? ORDER BY item_order ASC LIMIT 1 OFFSET ?",
                (self._name, offset)
            )
            result = cursor.fetchone()
            cursor.close()
            return json.loads(result['item_value']) if result else None

        else:
            raise TypeError("List indices must be integers or slices.")

    def _get_order_at_index(self, index: int) -> float:
        """Helper to get the float `item_order` at a specific index."""
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT item_order FROM beaver_lists WHERE list_name = ? ORDER BY item_order ASC LIMIT 1 OFFSET ?",
            (self._name, index)
        )
        result = cursor.fetchone()
        cursor.close()

        if result:
            return result[0]

        raise IndexError(f"{index} out of range.")

    def push(self, value: Any):
        """Pushes an item to the end of the list."""
        with self._conn:
            cursor = self._conn.cursor()
            cursor.execute("SELECT MAX(item_order) FROM beaver_lists WHERE list_name = ?", (self._name,))
            max_order = cursor.fetchone()[0] or 0.0
            new_order = max_order + 1.0

            cursor.execute(
                "INSERT INTO beaver_lists (list_name, item_order, item_value) VALUES (?, ?, ?)",
                (self._name, new_order, json.dumps(value))
            )

    def prepend(self, value: Any):
        """Prepends an item to the beginning of the list."""
        with self._conn:
            cursor = self._conn.cursor()
            cursor.execute("SELECT MIN(item_order) FROM beaver_lists WHERE list_name = ?", (self._name,))
            min_order = cursor.fetchone()[0] or 0.0
            new_order = min_order - 1.0

            cursor.execute(
                "INSERT INTO beaver_lists (list_name, item_order, item_value) VALUES (?, ?, ?)",
                (self._name, new_order, json.dumps(value))
            )

    def insert(self, index: int, value: Any):
        """Inserts an item at a specific index."""
        list_len = len(self)
        if index <= 0:
            self.prepend(value)
            return
        if index >= list_len:
            self.push(value)
            return

        # Midpoint insertion
        order_before = self._get_order_at_index(index - 1)
        order_after = self._get_order_at_index(index)

        new_order = order_before + (order_after - order_before) / 2.0

        with self._conn:
            self._conn.execute(
                "INSERT INTO beaver_lists (list_name, item_order, item_value) VALUES (?, ?, ?)",
                (self._name, new_order, json.dumps(value))
            )

    def pop(self) -> Any:
        """Removes and returns the last item from the list."""
        with self._conn:
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT rowid, item_value FROM beaver_lists WHERE list_name = ? ORDER BY item_order DESC LIMIT 1",
                (self._name,)
            )
            result = cursor.fetchone()
            if not result:
                return None

            rowid_to_delete, value_to_return = result
            cursor.execute("DELETE FROM beaver_lists WHERE rowid = ?", (rowid_to_delete,))
            return json.loads(value_to_return)

    def deque(self) -> Any:
        """Removes and returns the first item from the list."""
        with self._conn:
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT rowid, item_value FROM beaver_lists WHERE list_name = ? ORDER BY item_order ASC LIMIT 1",
                (self._name,)
            )
            result = cursor.fetchone()
            if not result:
                return None

            rowid_to_delete, value_to_return = result
            cursor.execute("DELETE FROM beaver_lists WHERE rowid = ?", (rowid_to_delete,))
            return json.loads(value_to_return)


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

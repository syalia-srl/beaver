import json
import sqlite3
import time
from typing import Any

from .lists import ListWrapper
from .subscribers import SubWrapper
from .collections import CollectionWrapper


class BeaverDB:
    """
    An embedded, multi-modal database in a single SQLite file.
    This class manages the database connection and table schemas.
    """

    def __init__(self, db_path: str):
        """
        Initializes the database connection and creates all necessary tables.

        Args:
            db_path: The path to the SQLite database file.
        """
        self._db_path = db_path
        # Enable WAL mode for better concurrency between readers and writers
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.row_factory = sqlite3.Row
        self._create_all_tables()

    def _create_all_tables(self):
        """Initializes all required tables in the database file."""
        self._create_kv_table()
        self._create_pubsub_table()
        self._create_list_table()
        self._create_collections_table()
        self._create_fts_table()
        self._create_edges_table()
        self._create_versions_table()

    def _create_kv_table(self):
        """Creates the key-value store table."""
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS _beaver_kv_store (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """
            )

    def _create_pubsub_table(self):
        """Creates the pub/sub log table."""
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS beaver_pubsub_log (
                    timestamp REAL PRIMARY KEY,
                    channel_name TEXT NOT NULL,
                    message_payload TEXT NOT NULL
                )
            """
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_pubsub_channel_timestamp
                ON beaver_pubsub_log (channel_name, timestamp)
            """
            )

    def _create_list_table(self):
        """Creates the lists table."""
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS beaver_lists (
                    list_name TEXT NOT NULL,
                    item_order REAL NOT NULL,
                    item_value TEXT NOT NULL,
                    PRIMARY KEY (list_name, item_order)
                )
            """
            )

    def _create_collections_table(self):
        """Creates the main table for storing documents and vectors."""
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS beaver_collections (
                    collection TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    item_vector BLOB,
                    metadata TEXT,
                    PRIMARY KEY (collection, item_id)
                )
            """
            )

    def _create_fts_table(self):
        """Creates the virtual FTS table for full-text search."""
        with self._conn:
            self._conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS beaver_fts_index USING fts5(
                    collection,
                    item_id,
                    field_path,
                    field_content,
                    tokenize = 'porter'
                )
            """
            )

    def _create_edges_table(self):
        """Creates the table for storing relationships between documents."""
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS beaver_edges (
                    collection TEXT NOT NULL,
                    source_item_id TEXT NOT NULL,
                    target_item_id TEXT NOT NULL,
                    label TEXT NOT NULL,
                    metadata TEXT,
                    PRIMARY KEY (collection, source_item_id, target_item_id, label)
                )
            """
            )

    def _create_versions_table(self):
        """Creates a table to track the version of each collection for caching."""
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS beaver_collection_versions (
                    collection_name TEXT PRIMARY KEY,
                    version INTEGER NOT NULL DEFAULT 0
                )
            """
            )

    def close(self):
        """Closes the database connection."""
        if self._conn:
            self._conn.close()

    # --- Factory and Passthrough Methods ---

    def set(self, key: str, value: Any):
        """
        Stores a JSON-serializable value for a given key.
        This operation is synchronous.
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
                (key, json_value),
            )

    def get(self, key: str) -> Any:
        """
        Retrieves a value for a given key.
        This operation is synchronous.
        """
        if not isinstance(key, str):
            raise TypeError("Key must be a string.")

        cursor = self._conn.cursor()
        cursor.execute("SELECT value FROM _beaver_kv_store WHERE key = ?", (key,))
        result = cursor.fetchone()
        cursor.close()

        return json.loads(result["value"]) if result else None

    def list(self, name: str) -> ListWrapper:
        """Returns a wrapper object for interacting with a named list."""
        if not isinstance(name, str) or not name:
            raise TypeError("List name must be a non-empty string.")
        return ListWrapper(name, self._conn)

    def collection(self, name: str) -> CollectionWrapper:
        """Returns a wrapper for interacting with a document collection."""
        return CollectionWrapper(name, self._conn)

    def publish(self, channel_name: str, payload: Any):
        """Publishes a JSON-serializable message to a channel. This is synchronous."""
        if not isinstance(channel_name, str) or not channel_name:
            raise ValueError("Channel name must be a non-empty string.")
        try:
            json_payload = json.dumps(payload)
        except TypeError as e:
            raise TypeError("Message payload must be JSON-serializable.") from e

        with self._conn:
            self._conn.execute(
                "INSERT INTO beaver_pubsub_log (timestamp, channel_name, message_payload) VALUES (?, ?, ?)",
                (time.time(), channel_name, json_payload),
            )

    def subscribe(self, channel_name: str) -> SubWrapper:
        """Subscribes to a channel, returning a synchronous iterator."""
        return SubWrapper(self._conn, channel_name)

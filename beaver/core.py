import sqlite3
import threading
import warnings
from typing import List, Type

from .types import JsonSerializable
from .blobs import BlobManager
from .channels import ChannelManager
from .collections import CollectionManager, Document
from .dicts import DictManager
from .lists import ListManager
from .locks import LockManager
from .logs import LogManager
from .queues import QueueManager


class BeaverDB:
    """
    An embedded, multi-modal database in a single SQLite file.
    This class manages thread-safe database connections and table schemas.
    """

    def __init__(self, db_path: str, timeout: float = 30.0):
        """
        Initializes the database connection and creates all necessary tables.

        Args:
            db_path: The path to the SQLite database file.
        """
        self._db_path = db_path
        self._timeout = timeout
        # This object will store a different connection for each thread.
        self._thread_local = threading.local()

        self._in_memory = db_path == ":memory:"
        self._main_thread = threading.current_thread().native_id

        self._channels: dict[str, ChannelManager] = {}
        self._channels_lock = threading.Lock()
        self._collections: dict[str, CollectionManager] = {}
        self._collections_lock = threading.Lock()

        # Initialize the schemas. This will implicitly create the first
        # connection for the main thread via the `connection` property.
        self._create_all_tables()

        # check current version against the version stored
        self._check_version()

    def _check_version(self):
        from beaver import __version__

        db_version = self.dict("__metadata__").get("version", __version__)
        self.dict("__metadata__")["version"] = db_version

        if db_version != __version__:
            warnings.warn(
                f"Version mismatch. DB was created with version {db_version}, but the library version is {__version__}.",
                stacklevel=3,
            )

    @property
    def version(self):
        return self.dict("__metadata__")["version"]

    @property
    def connection(self) -> sqlite3.Connection:
        """
        Provides a thread-safe SQLite connection.

        Each thread will receive its own dedicated connection object.
        The connection is created on the first access and then reused for
        all subsequent calls within the same thread.
        """
        if self._in_memory:
            current_thread = threading.current_thread().native_id
            if current_thread != self._main_thread:
                raise TypeError("Cannot use BeaverDB in multi-threaded context with :memory: path.")

        # Check if a connection is already stored for this thread
        conn = getattr(self._thread_local, "conn", None)

        if conn is None:
            # No connection for this thread yet, so create one.
            # We no longer need check_same_thread=False, restoring thread safety.
            conn = sqlite3.connect(self._db_path, timeout=self._timeout)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.row_factory = sqlite3.Row
            self._thread_local.conn = conn

        return conn

    def _create_all_tables(self):
        """Initializes all required tables in the database file."""
        with self.connection:
            self._create_blobs_table()
            self._create_collections_table()
            self._create_dict_table()
            self._create_edges_table()
            self._create_fts_table()
            self._create_list_table()
            self._create_logs_table()
            self._create_priority_queue_table()
            self._create_pubsub_table()
            self._create_trigrams_table()
            self._create_versions_table()
            self._create_locks_table()
            self._create_vector_change_log_table()

    def _create_vector_change_log_table(self):
        """Creates the unified log for vector insertions and deletions."""
        # operation_type: 1 = INSERT, 2 = DELETE
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS _vector_change_log (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                collection_name TEXT NOT NULL,
                item_id TEXT NOT NULL,
                operation_type INTEGER NOT NULL
            )
            """
        )
        self.connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_vcl_lookup
            ON _vector_change_log (collection_name, log_id)
            """
        )

    def _create_locks_table(self):  # <-- Add this new method
        """Creates the table for managing inter-process lock waiters."""
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS beaver_lock_waiters (
                lock_name TEXT NOT NULL,
                waiter_id TEXT NOT NULL,
                requested_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                PRIMARY KEY (lock_name, requested_at)
            )
            """
        )
        # Index for fast cleanup of expired locks
        self.connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_lock_expires
            ON beaver_lock_waiters (lock_name, expires_at)
            """
        )
        # Index for fast deletion by the lock holder
        self.connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_lock_waiter_id
            ON beaver_lock_waiters (lock_name, waiter_id)
            """
        )

    def _create_logs_table(self):
        """Creates the table for time-indexed logs."""
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS beaver_logs (
                log_name TEXT NOT NULL,
                timestamp REAL NOT NULL,
                data TEXT NOT NULL,
                PRIMARY KEY (log_name, timestamp)
            )
            """
        )
        self.connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_logs_timestamp
            ON beaver_logs (log_name, timestamp)
            """
        )

    def _create_blobs_table(self):
        """Creates the table for storing named blobs."""
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS beaver_blobs (
                store_name TEXT NOT NULL,
                key TEXT NOT NULL,
                data BLOB NOT NULL,
                metadata TEXT,
                PRIMARY KEY (store_name, key)
            )
            """
        )

    def _create_priority_queue_table(self):
        """Creates the priority queue table and its performance index."""
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS beaver_priority_queues (
                queue_name TEXT NOT NULL,
                priority REAL NOT NULL,
                timestamp REAL NOT NULL,
                data TEXT NOT NULL
            )
            """
        )
        self.connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_priority_queue_order
            ON beaver_priority_queues (queue_name, priority ASC, timestamp ASC)
            """
        )

    def _create_dict_table(self):
        """Creates the namespaced dictionary table."""
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS beaver_dicts (
                dict_name TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                expires_at REAL,
                PRIMARY KEY (dict_name, key)
            )
        """
        )

    def _create_pubsub_table(self):
        """Creates the pub/sub log table."""
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS beaver_pubsub_log (
                timestamp REAL PRIMARY KEY,
                channel_name TEXT NOT NULL,
                message_payload TEXT NOT NULL
            )
        """
        )
        self.connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_pubsub_channel_timestamp
            ON beaver_pubsub_log (channel_name, timestamp)
        """
        )

    def _create_list_table(self):
        """Creates the lists table."""
        self.connection.execute(
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
        self.connection.execute(
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
        self.connection.execute(
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

    def _create_trigrams_table(self):
        """Creates the table for the fuzzy search trigram index."""
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS beaver_trigrams (
                collection TEXT NOT NULL,
                item_id TEXT NOT NULL,
                field_path TEXT NOT NULL,
                trigram TEXT NOT NULL,
                PRIMARY KEY (collection, field_path, trigram, item_id)
            )
            """
        )
        self.connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_trigram_lookup
            ON beaver_trigrams (collection, trigram, field_path)
            """
        )

    def _create_edges_table(self):
        """Creates the table for storing relationships between documents."""
        self.connection.execute(
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
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS beaver_collection_versions (
                collection_name TEXT PRIMARY KEY,
                base_version INTEGER NOT NULL DEFAULT 0
            )
        """
        )

    def close(self):
        """Closes the database connection."""
        if self.connection:
            # Cleanly shut down any active polling threads before closing
            with self._channels_lock:
                for channel in self._channels.values():
                    channel.close()
            self.connection.close()

    # --- Factory and Passthrough Methods ---

    def dict[T](self, name: str, model: type[T] | None = None) -> DictManager[T]:
        """
        Returns a wrapper object for interacting with a named dictionary.
        If model is defined, it should be a type used for automatic (de)serialization.
        """
        if not isinstance(name, str) or not name:
            raise TypeError("Dictionary name must be a non-empty string.")

        if model and not isinstance(model, JsonSerializable):
            raise TypeError("The model parameter must be a JsonSerializable class.")

        return DictManager(name, self, model)

    def list[T](self, name: str, model: type[T] | None = None) -> ListManager[T]:
        """
        Returns a wrapper object for interacting with a named list.
        If model is defined, it should be a type used for automatic (de)serialization.
        """
        if not isinstance(name, str) or not name:
            raise TypeError("List name must be a non-empty string.")

        if model and not isinstance(model, JsonSerializable):
            raise TypeError("The model parameter must be a JsonSerializable class.")

        return ListManager(name, self, model)

    def queue[T](self, name: str, model: type[T] | None = None) -> QueueManager[T]:
        """
        Returns a wrapper object for interacting with a persistent priority queue.
        If model is defined, it should be a type used for automatic (de)serialization.
        """
        if not isinstance(name, str) or not name:
            raise TypeError("Queue name must be a non-empty string.")

        if model and not isinstance(model, JsonSerializable):
            raise TypeError("The model parameter must be a JsonSerializable class.")

        return QueueManager(name, self, model)

    def collection[D: Document](
        self, name: str, model: Type[D] | None = None
    ) -> CollectionManager[D]:
        """
        Returns a singleton CollectionManager instance for interacting with a
        document collection.
        """
        if not isinstance(name, str) or not name:
            raise TypeError("Collection name must be a non-empty string.")

        # Use a thread-safe lock to ensure only one CollectionManager object is
        # created per name. This is crucial for managing the in-memory state
        # of the vector index consistently.
        with self._collections_lock:
            if name not in self._collections:
                self._collections[name] = CollectionManager(name, self, model=model)

            return self._collections[name]

    def channel[T](self, name: str, model: type[T] | None = None) -> ChannelManager[T]:
        """
        Returns a singleton Channel instance for high-efficiency pub/sub.
        """
        if not isinstance(name, str) or not name:
            raise ValueError("Channel name must be a non-empty string.")

        # Use a thread-safe lock to ensure only one Channel object is created per name.
        with self._channels_lock:
            if name not in self._channels:
                self._channels[name] = ChannelManager(name, self, model=model)
            return self._channels[name]

    def blob[M](self, name: str, model: type[M] | None = None) -> BlobManager[M]:
        """Returns a wrapper object for interacting with a named blob store."""
        if not isinstance(name, str) or not name:
            raise TypeError("Blob store name must be a non-empty string.")

        return BlobManager(name, self, model)

    def log[T](self, name: str, model: type[T] | None = None) -> LogManager[T]:
        """
        Returns a wrapper for interacting with a named, time-indexed log.
        If model is defined, it should be a type used for automatic (de)serialization.
        """
        if not isinstance(name, str) or not name:
            raise TypeError("Log name must be a non-empty string.")

        if model and not isinstance(model, JsonSerializable):
            raise TypeError("The model parameter must be a JsonSerializable class.")

        return LogManager(name, self, model)

    def lock(
        self,
        name: str,
        timeout: float | None = None,
        lock_ttl: float = 60.0,
        poll_interval: float = 0.1,
    ) -> LockManager:
        """
        Returns an inter-process lock manager for a given lock name.

        Args:
            name: The unique name of the lock (e.g., "run_compaction").
            timeout: Max seconds to wait to acquire the lock.
                    If None, it will wait forever.
            lock_ttl: Max seconds the lock can be held. If the process crashes,
                    the lock will auto-expire after this time.
            poll_interval: Seconds to wait between polls. Shorter intervals
                        are more responsive but create more DB I/O.
        """
        return LockManager(self, name, timeout, lock_ttl, poll_interval)

    # --- New Properties for Name Discovery ---

    @property
    def dicts(self) -> List[str]:
        """Returns a list of all existing user-defined dictionary names."""
        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT DISTINCT dict_name FROM beaver_dicts
            WHERE dict_name NOT LIKE '__%'
            ORDER BY dict_name
            """
        )
        names = [row["dict_name"] for row in cursor.fetchall()]
        cursor.close()
        return names

    @property
    def lists(self) -> List[str]:
        """Returns a list of all existing user-defined list names."""
        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT DISTINCT list_name FROM beaver_lists
            WHERE list_name NOT LIKE '__%'
            ORDER BY list_name
            """
        )
        names = [row["list_name"] for row in cursor.fetchall()]
        cursor.close()
        return names

    @property
    def queues(self) -> List[str]:
        """Returns a list of all existing user-defined queue names."""
        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT DISTINCT queue_name FROM beaver_priority_queues
            WHERE queue_name NOT LIKE '__%'
            ORDER BY queue_name
            """
        )
        names = [row["queue_name"] for row in cursor.fetchall()]
        cursor.close()
        return names

    @property
    def collections(self) -> List[str]:
        """Returns a list of all existing user-defined collection names."""
        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT DISTINCT collection FROM beaver_collections
            WHERE collection NOT LIKE '__%'
            ORDER BY collection
            """
        )
        names = [row["collection"] for row in cursor.fetchall()]
        cursor.close()
        return names

    @property
    def channels(self) -> List[str]:
        """Returns a list of all existing channel names that have messages."""
        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT DISTINCT channel_name FROM beaver_pubsub_log
            ORDER BY channel_name
            """
        )
        names = [row["channel_name"] for row in cursor.fetchall()]
        cursor.close()
        return names

    @property
    def blobs(self) -> List[str]:
        """Returns a list of all existing user-defined blob store names."""
        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT DISTINCT store_name FROM beaver_blobs
            WHERE store_name NOT LIKE '__%'
            ORDER BY store_name
            """
        )
        names = [row["store_name"] for row in cursor.fetchall()]
        cursor.close()
        return names

    @property
    def logs(self) -> List[str]:
        """Returns a list of all existing log names."""
        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT DISTINCT log_name FROM beaver_logs
            ORDER BY log_name
            """
        )
        names = [row["log_name"] for row in cursor.fetchall()]
        cursor.close()
        return names

    @property
    def locks(self) -> List[str]:
        """Returns a list of all active, user-defined lock names."""
        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT DISTINCT lock_name FROM beaver_lock_waiters
            WHERE lock_name NOT LIKE '__%'
            ORDER BY lock_name
            """
        )
        names = [row["lock_name"] for row in cursor.fetchall()]
        cursor.close()
        return names
import sqlite3
import threading
import warnings
from typing import List, Type

from beaver.cache import DummyCache, ICache, LocalCache
from beaver.manager import ManagerBase

from .types import IDatabase, JsonSerializable
from .blobs import BlobManager
from .channels import ChannelManager
from .collections import CollectionManager, Document
from .dicts import DictManager
from .lists import ListManager
from .locks import LockManager
from .logs import LogManager
from .queues import QueueManager


class BeaverDB(IDatabase):
    """
    An embedded, multi-modal database in a single SQLite file.
    This class manages thread-safe database connections and table schemas.
    """

    def __init__(self, db_path: str, timeout: float = 30.0, enable_cache: bool = True):
        """
        Initializes the database connection and creates all necessary tables.

        Args:
            db_path: The path to the SQLite database file.
        """
        self._db_path = db_path
        self._timeout = timeout
        self._enable_cache = enable_cache

        # This object will store a different connection for each thread.
        self._thread_local = threading.local()
        self._closed = threading.Event()  # Flag to indicate if DB is closed

        self._in_memory = db_path == ":memory:"
        self._main_thread = threading.current_thread().native_id

        # Lock and data structure for managing singleton instances
        self._manager_cache: dict[tuple[type, str], ManagerBase] = {}
        self._manager_cache_lock = threading.Lock()

        # Initialize the schemas. This will implicitly create the first
        # connection for the main thread via the `connection` property.
        self._create_all_tables()

        # check current version against the version stored
        self._check_version()

    def singleton[T: JsonSerializable, M: ManagerBase](
        self, cls: Type[M], name: str, model: Type[T] | None = None, **kwargs
    ) -> M:
        """
        Factory method to get a process-level singleton for a manager.

        Caches the instance on this db object to ensure that, e.g.,
        db.dict("foo") always returns the same object.
        """
        cache_key = (cls, name)

        if not issubclass(cls, ManagerBase):
            raise TypeError("cls must be a subclass of ManagerBase.")

        if not name:
            raise ValueError("name must be a non-empty string.")

        if model is not None and not isinstance(model, JsonSerializable):
            raise TypeError("model must be a JsonSerializable class.")

        # Use the db's lock for thread-safe cache access
        with self._manager_cache_lock:
            if self._closed.is_set():
                raise ConnectionError("BeaverDB instance is closed.")

            instance: ManagerBase[T] | None = self._manager_cache.get(cache_key)

            if instance is None:
                # Create the instance, passing 'self' as the 'db' argument,
                # plus all other args.
                instance = cls(name=name, db=self, model=model, **kwargs)
                self._manager_cache[cache_key] = instance

            return instance

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
        if self._closed.is_set():
            raise ConnectionError("BeaverDB instance is closed.")

        # Disallow multi-threaded use of in-memory DBs
        if self._in_memory:
            current_thread = threading.current_thread().native_id

            if current_thread != self._main_thread:
                raise TypeError(
                    "Cannot use BeaverDB in multi-threaded context with :memory: path."
                )

        # Check if a connection is already stored for this thread
        conn = getattr(self._thread_local, "conn", None)

        if conn is None:
            if self._closed.is_set():
                raise ConnectionError("BeaverDB instance is closed.")

            # No connection for this thread yet, so create one.
            conn = sqlite3.connect(self._db_path, timeout=self._timeout)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.row_factory = sqlite3.Row
            self._thread_local.conn = conn

        return conn

    def cache(self, key: str = "global") -> ICache:
        """Returns a thread-local cache that is always valid."""
        if self._closed.is_set():
            raise ConnectionError("BeaverDB instance is closed.")

        if not self._enable_cache:
            return DummyCache.singleton()

        cache = getattr(self._thread_local, f"cache_{key}", None)

        if cache is None:
            cache = LocalCache(f"{self._db_path}-wal")
            setattr(self._thread_local, f"cache_{key}", cache)

        return cache

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
        """
        Closes the database connection for the current thread and shuts down
        all background polling threads (e.g., for pub/sub channels).

        Once closed, any attempt to access the connection will raise an error.
        """
        if self._closed.is_set():
            return  # Already closed

        self._closed.set()

        # Shut down all background services (like Channel pollers)
        # We must lock the cache to safely iterate over it
        with self._manager_cache_lock:
            for instance in self._manager_cache.values():
                # Check if the instance has a 'close' method and call it
                if hasattr(instance, "close") and callable(instance.close):
                    try:
                        instance.close()
                    except Exception as e:
                        warnings.warn(
                            f"Error closing manager instance {instance}. Exception ignored: {str(e)}.",
                            stacklevel=2,
                        )

            self._manager_cache.clear()

        # Close the connection for the *current* thread
        conn = getattr(self._thread_local, "conn", None)
        if conn is not None:
            try:
                conn.close()
                del self._thread_local.conn
            except Exception as e:
                warnings.warn(
                    f"Error closing connection. Exception ignored: {str(e)}.",
                    stacklevel=2,
                )

    # --- Factory and Passthrough Methods ---

    def dict[T: JsonSerializable](
        self, name: str, model: type[T] | None = None
    ) -> DictManager[T]:
        """
        Returns a wrapper object for interacting with a named dictionary.
        If model is defined, it should be a type used for automatic (de)serialization.
        """
        return self.singleton(DictManager, name, model)

    def list[T: JsonSerializable](
        self, name: str, model: type[T] | None = None
    ) -> ListManager[T]:
        """
        Returns a wrapper object for interacting with a named list.
        If model is defined, it should be a type used for automatic (de)serialization.
        """
        return self.singleton(ListManager, name, model)

    def queue[T: JsonSerializable](
        self, name: str, model: type[T] | None = None
    ) -> QueueManager[T]:
        """
        Returns a wrapper object for interacting with a persistent priority queue.
        If model is defined, it should be a type used for automatic (de)serialization.
        """
        return self.singleton(QueueManager, name, model)

    def collection[D: Document](
        self, name: str, model: Type[D] | None = None
    ) -> CollectionManager[D]:
        """
        Returns a singleton CollectionManager instance for interacting with a
        document collection.
        """
        return self.singleton(CollectionManager, name, model)

    def channel[T: JsonSerializable](
        self, name: str, model: type[T] | None = None
    ) -> ChannelManager[T]:
        """
        Returns a singleton Channel instance for high-efficiency pub/sub.
        """
        return self.singleton(ChannelManager, name, model)

    def blob[M: JsonSerializable](
        self, name: str, model: type[M] | None = None
    ) -> BlobManager[M]:
        """Returns a wrapper object for interacting with a named blob store."""
        return self.singleton(BlobManager, name, model)

    def log[T: JsonSerializable](
        self, name: str, model: type[T] | None = None
    ) -> LogManager[T]:
        """
        Returns a wrapper for interacting with a named, time-indexed log.
        If model is defined, it should be a type used for automatic (de)serialization.
        """
        return self.singleton(LogManager, name, model)

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
            name: The unique name of the lock.
            timeout: Max seconds to wait to acquire the lock.
                    If None, it will wait forever.
            lock_ttl: Max seconds the lock can be held. If the process crashes,
                    the lock will auto-expire after this time.
            poll_interval: Seconds to wait between polls. Shorter intervals
                        are more responsive but create more DB I/O.
        """
        if self._closed.is_set():
            raise ConnectionError("BeaverDB instance is closed.")

        return LockManager(self, name, timeout, lock_ttl, poll_interval)

    # --- Properties for Name Discovery ---

    def _get_distinct_names(
        self,
        table_name: str,
        column_name: str,
    ) -> List[str]:
        """
        A parameterized helper to get a distinct list of user-defined names
        from a table, excluding internal names (those starting with '__').
        """
        cursor = self.connection.cursor()

        # Build the query
        sql = f"""
        SELECT DISTINCT {column_name}
        FROM {table_name}
        WHERE {column_name} NOT LIKE '__%'
        ORDER BY {column_name} ASC
        """

        cursor.execute(sql)

        names = [row[column_name] for row in cursor.fetchall()]
        cursor.close()
        return names

    @property
    def dicts(self) -> List[str]:
        """Returns a list of all existing user-defined dictionary names."""
        return self._get_distinct_names(
            table_name="beaver_dicts", column_name="dict_name"
        )

    @property
    def lists(self) -> List[str]:
        """Returns a list of all existing user-defined list names."""
        return self._get_distinct_names(
            table_name="beaver_lists", column_name="list_name"
        )

    @property
    def queues(self) -> List[str]:
        """Returns a list of all existing user-defined queue names."""
        return self._get_distinct_names(
            table_name="beaver_priority_queues", column_name="queue_name"
        )

    @property
    def collections(self) -> List[str]:
        """Returns a list of all existing user-defined collection names."""
        return self._get_distinct_names(
            table_name="beaver_collections", column_name="collection"
        )

    @property
    def channels(self) -> List[str]:
        """Returns a list of all existing user-defined channel names."""
        return self._get_distinct_names(
            table_name="beaver_pubsub_log",
            column_name="channel_name",
        )

    @property
    def blobs(self) -> List[str]:
        """Returns a list of all existing user-defined blob store names."""
        return self._get_distinct_names(
            table_name="beaver_blobs", column_name="store_name"
        )

    @property
    def logs(self) -> List[str]:
        """Returns a list of all existing user-defined log names."""
        return self._get_distinct_names(
            table_name="beaver_logs", column_name="log_name"
        )

    @property
    def locks(self) -> List[str]:
        """Returns a list of all active, user-defined lock names."""
        return self._get_distinct_names(
            table_name="beaver_lock_waiters", column_name="lock_name"
        )

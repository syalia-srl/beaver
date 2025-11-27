import asyncio
import threading
import warnings
import weakref
from typing import Any, Callable, Type, AsyncContextManager

import aiosqlite
from pydantic import BaseModel

# Note: These imports will eventually be updated to "Async..." versions
# as we progress through the file-by-file refactor.
from .blobs import BlobManager
from .cache import DummyCache, LocalCache
from .channels import ChannelManager
from .collections import CollectionManager, Document
from .dicts import DictManager
from .lists import ListManager
from .locks import AsyncBeaverLock
from .logs import LogManager
from .manager import ManagerBase
from .queues import QueueManager
from .sketches import SketchManager
from .bridge import BeaverBridge


class Event(BaseModel):
    topic: str
    event: str
    payload: dict


class _TransactionContext:
    """
    Helper context manager for AsyncBeaverDB.transaction().
    Ensures serializability on the shared aiosqlite connection.
    """

    def __init__(self, connection: aiosqlite.Connection, lock: asyncio.Lock):
        self.conn = connection
        self.lock = lock

    async def __aenter__(self):
        # 1. Wait for other coroutines to finish their transactions
        await self.lock.acquire()

        # 2. Start the DB transaction explicitly
        # 'IMMEDIATE' is crucial to prevent deadlocks with other processes
        await self.conn.execute("BEGIN IMMEDIATE")
        return self

    async def __aexit__(self, exc_type, exc, tb):
        try:
            if exc_type:
                await self.conn.rollback()
            else:
                await self.conn.commit()
        finally:
            # 3. Always release the lock so the next task can run
            self.lock.release()


class AsyncBeaverDB:
    """
    The Async-First Core Engine of BeaverDB.

    This class manages the single aiosqlite connection and strictly runs
    within an asyncio event loop. It is NOT thread-safe; it is designed
    to be owned by a single thread (the Reactor Thread).
    """

    def __init__(
        self,
        db_path: str,
        /,
        *,
        connection_timeout: float = 30.0,
        cache_timeout: float = 0.0,
        pragma_wal: bool = True,
        pragma_synchronous: bool = False,
        pragma_temp_memory: bool = True,
        pragma_mmap_size: int = 256 * 1024 * 1024,
    ):
        self._db_path = db_path
        self._timeout = connection_timeout
        self._cache_timeout = cache_timeout

        # The Single Source of Truth Connection
        self._connection: aiosqlite.Connection | None = None

        # Transaction Serializer Lock
        # Ensures that "check-then-act" operations (like locks) are atomic
        # relative to other tasks on this loop.
        self._tx_lock = asyncio.Lock()

        # Manager Singleton Cache
        self._manager_cache: dict[tuple[type, str], Any] = {}

        # Store pragma settings
        self._pragma_wal = pragma_wal
        self._pragma_synchronous = pragma_synchronous
        self._pragma_temp_memory = pragma_temp_memory
        self._pragma_mmap_size = pragma_mmap_size

        # Pub/Sub Registry (To be reimplemented in Phase 4)
        # self._event_callbacks: dict[str, list[Callable]] = {}

    async def connect(self):
        """
        Initializes the async database connection and creates tables.
        Must be awaited before using the DB.
        """
        if self._connection is not None:
            return

        self._connection = await aiosqlite.connect(self._db_path, timeout=self._timeout)
        self._connection.row_factory = aiosqlite.Row

        # Apply Pragmas
        if self._pragma_wal:
            await self._connection.execute("PRAGMA journal_mode = WAL;")

        if self._pragma_synchronous:
            await self._connection.execute("PRAGMA synchronous = FULL;")
        else:
            await self._connection.execute("PRAGMA synchronous = NORMAL;")

        if self._pragma_temp_memory:
            await self._connection.execute("PRAGMA temp_store = MEMORY;")

        if self._pragma_mmap_size > 0:
            await self._connection.execute(
                f"PRAGMA mmap_size = {self._pragma_mmap_size};"
            )

        await self._create_all_tables()
        # await self._check_version()

        return self

    async def close(self):
        """Closes the database connection."""
        if self._connection:
            await self._connection.close()
            self._connection = None

        # Clear cache to allow GC
        self._manager_cache.clear()

    async def __aenter__(self):
        return await self.connect()

    async def __aexit__(self, *args, **kwargs):
        await self.close()

    @property
    def connection(self) -> aiosqlite.Connection:
        """
        Returns the raw aiosqlite connection.
        Raises an error if not connected.
        """
        if self._connection is None:
            raise ConnectionError(
                "AsyncBeaverDB is not connected. Await .connect() first."
            )

        return self._connection

    def transaction(self) -> AsyncContextManager:
        """
        Returns an async context manager for an atomic transaction.
        Use: async with db.transaction(): ...
        """
        return _TransactionContext(self.connection, self._tx_lock)

    async def _create_all_tables(self):
        """Initializes all required tables with the new __beaver__ naming convention."""
        # Note: We use execute() directly here as these are DDL statements
        # and don't strictly require the transaction lock (sqlite handles DDL locking).

        c = self.connection

        # Blobs
        await c.execute(
            """
            CREATE TABLE IF NOT EXISTS __beaver_blobs__ (
                store_name TEXT NOT NULL,
                key TEXT NOT NULL,
                data BLOB NOT NULL,
                metadata TEXT,
                PRIMARY KEY (store_name, key)
            )
        """
        )

        # Cache Versioning
        await c.execute(
            """
            CREATE TABLE IF NOT EXISTS __beaver_manager_versions__ (
                namespace TEXT PRIMARY KEY,
                version INTEGER NOT NULL DEFAULT 0
            )
        """
        )

        # Collections (Vectors)
        await c.execute(
            """
            CREATE TABLE IF NOT EXISTS __beaver_collections__ (
                collection TEXT NOT NULL,
                item_id TEXT NOT NULL,
                item_vector BLOB,
                metadata TEXT,
                PRIMARY KEY (collection, item_id)
            )
        """
        )

        # Dicts
        await c.execute(
            """
            CREATE TABLE IF NOT EXISTS __beaver_dicts__ (
                dict_name TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                expires_at REAL,
                PRIMARY KEY (dict_name, key)
            )
        """
        )

        # Edges (Graph)
        await c.execute(
            """
            CREATE TABLE IF NOT EXISTS __beaver_edges__ (
                collection TEXT NOT NULL,
                source_item_id TEXT NOT NULL,
                target_item_id TEXT NOT NULL,
                label TEXT NOT NULL,
                metadata TEXT,
                PRIMARY KEY (collection, source_item_id, target_item_id, label)
            )
        """
        )

        # FTS (Virtual Table)
        await c.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS __beaver_fts_index__ USING fts5(
                collection,
                item_id,
                field_path,
                field_content,
                tokenize = 'porter'
            )
        """
        )

        # Lists
        await c.execute(
            """
            CREATE TABLE IF NOT EXISTS __beaver_lists__ (
                list_name TEXT NOT NULL,
                item_order REAL NOT NULL,
                item_value TEXT NOT NULL,
                PRIMARY KEY (list_name, item_order)
            )
        """
        )

        # Locks
        await c.execute(
            """
            CREATE TABLE IF NOT EXISTS __beaver_lock_waiters__ (
                lock_name TEXT NOT NULL,
                waiter_id TEXT NOT NULL,
                requested_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                PRIMARY KEY (lock_name, requested_at)
            )
        """
        )
        await c.execute(
            "CREATE INDEX IF NOT EXISTS idx_lock_expires ON __beaver_lock_waiters__ (lock_name, expires_at)"
        )
        await c.execute(
            "CREATE INDEX IF NOT EXISTS idx_lock_waiter_id ON __beaver_lock_waiters__ (lock_name, waiter_id)"
        )

        # Logs
        await c.execute(
            """
            CREATE TABLE IF NOT EXISTS __beaver_logs__ (
                log_name TEXT NOT NULL,
                timestamp REAL NOT NULL,
                data TEXT NOT NULL,
                PRIMARY KEY (log_name, timestamp)
            )
        """
        )
        await c.execute(
            "CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON __beaver_logs__ (log_name, timestamp)"
        )

        # Priority Queues
        await c.execute(
            """
            CREATE TABLE IF NOT EXISTS __beaver_priority_queues__ (
                queue_name TEXT NOT NULL,
                priority REAL NOT NULL,
                timestamp REAL NOT NULL,
                data TEXT NOT NULL
            )
        """
        )
        await c.execute(
            "CREATE INDEX IF NOT EXISTS idx_priority_queue_order ON __beaver_priority_queues__ (queue_name, priority ASC, timestamp ASC)"
        )

        # PubSub
        await c.execute(
            """
            CREATE TABLE IF NOT EXISTS __beaver_pubsub_log__ (
                timestamp REAL PRIMARY KEY,
                channel_name TEXT NOT NULL,
                message_payload TEXT NOT NULL
            )
        """
        )
        await c.execute(
            "CREATE INDEX IF NOT EXISTS idx_pubsub_channel_timestamp ON __beaver_pubsub_log__ (channel_name, timestamp)"
        )

        # Trigrams (Fuzzy)
        await c.execute(
            """
            CREATE TABLE IF NOT EXISTS __beaver_trigrams__ (
                collection TEXT NOT NULL,
                item_id TEXT NOT NULL,
                field_path TEXT NOT NULL,
                trigram TEXT NOT NULL,
                PRIMARY KEY (collection, field_path, trigram, item_id)
            )
        """
        )
        await c.execute(
            "CREATE INDEX IF NOT EXISTS idx_trigram_lookup ON __beaver_trigrams__ (collection, trigram, field_path)"
        )

        # Vector Change Log
        await c.execute(
            """
            CREATE TABLE IF NOT EXISTS __beaver_vector_change_log__ (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                collection_name TEXT NOT NULL,
                item_id TEXT NOT NULL,
                operation_type INTEGER NOT NULL
            )
        """
        )
        await c.execute(
            "CREATE INDEX IF NOT EXISTS idx_vcl_lookup ON __beaver_vector_change_log__ (collection_name, log_id)"
        )

        # Collection Versions
        await c.execute(
            """
            CREATE TABLE IF NOT EXISTS __beaver_collection_versions__ (
                collection_name TEXT PRIMARY KEY,
                base_version INTEGER NOT NULL DEFAULT 0
            )
        """
        )

        # Sketches
        await c.execute(
            """
            CREATE TABLE IF NOT EXISTS __beaver_sketches__ (
                name TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                capacity INTEGER NOT NULL,
                error_rate REAL NOT NULL,
                data BLOB NOT NULL
            )
        """
        )

        await self.connection.commit()

    def singleton(self, cls, name, **kwargs):
        """
        Factory method to get a singleton manager.
        Since this runs on the event loop, no locks are needed.
        """
        cache_key = (cls, name)

        if cache_key not in self._manager_cache:
            # We pass 'self' (AsyncBeaverDB) as the db interface
            instance = cls(name=name, db=self, **kwargs)
            self._manager_cache[cache_key] = instance

        return self._manager_cache[cache_key]

    # --- Factory Methods (Internal) ---
    # These return the raw Async Managers.
    # Note: These manager classes will be refactored in Phase 3.

    def dict(self, name: str, model: type | None = None, secret: str | None = None):
        return self.singleton(DictManager, name, model=model, secret=secret)

    def list(self, name: str, model: type | None = None):
        return self.singleton(ListManager, name, model=model)

    def queue(self, name: str, model: type | None = None):
        return self.singleton(QueueManager, name, model=model)

    def collection(self, name: str, model: Type | None = None):
        return self.singleton(CollectionManager, name, model=model)

    def channel(self, name: str, model: type | None = None):
        return self.singleton(ChannelManager, name, model=model)

    def blob(self, name: str, model: type | None = None):
        return self.singleton(BlobManager, name, model=model)

    def log(self, name: str, model: type | None = None):
        return self.singleton(LogManager, name, model=model)

    def lock(
        self, name: str, timeout=None, lock_ttl=60.0, poll_interval=0.1
    ) -> AsyncBeaverLock:
        return AsyncBeaverLock(self, name, timeout, lock_ttl, poll_interval)

    def sketch(self, name: str, capacity=1_000_000, error_rate=0.01, model=None):
        return self.singleton(
            SketchManager, name, capacity=capacity, error_rate=error_rate, model=model
        )

    def cache(self, key: str = "global"):
        # Temporary stub: Caching will be revisited
        return DummyCache.singleton()


class BeaverDB:
    """
    The Synchronous Facade (Portal).

    This class starts a background thread with an asyncio loop and
    proxies all requests to the AsyncBeaverDB engine via BeaverBridge.
    """

    def __init__(self, db_path: str, /, **kwargs):
        # 1. Start the Reactor Thread
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever, daemon=True, name="BeaverDB-Reactor"
        )
        self._thread.start()

        # 2. Initialize the Engine on the Reactor Thread
        async def init_engine():
            db = AsyncBeaverDB(db_path, **kwargs)
            await db.connect()
            return db

        future = asyncio.run_coroutine_threadsafe(init_engine(), self._loop)
        self._async_db = future.result()
        self._closed = False

    def close(self):
        """Shuts down the reactor thread and closes the DB."""
        if self._closed:
            return

        async def shutdown():
            await self._async_db.close()

        future = asyncio.run_coroutine_threadsafe(shutdown(), self._loop)
        future.result()

        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=1.0)
        self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _get_manager(self, method_name: str, *args, **kwargs) -> Any:
        """
        Helper to invoke a factory method on the Async Engine and wrap the result.
        Executing on the loop ensures the singleton cache is accessed safely.
        """

        async def factory_call():
            method = getattr(self._async_db, method_name)
            return method(*args, **kwargs)

        future = asyncio.run_coroutine_threadsafe(factory_call(), self._loop)
        async_manager = future.result()

        # Wrap the Async Manager in the Bridge
        return BeaverBridge(async_manager, self._loop)

    # --- Public API (Proxies) ---

    def dict(self, name: str, model: type | None = None, secret: str | None = None):
        return self._get_manager("dict", name, model, secret)

    def list(self, name: str, model: type | None = None):
        return self._get_manager("list", name, model)

    def queue(self, name: str, model: type | None = None):
        return self._get_manager("queue", name, model)

    def collection(self, name: str, model: Type | None = None):
        return self._get_manager("collection", name, model)

    def channel(self, name: str, model: type | None = None):
        return self._get_manager("channel", name, model)

    def blob(self, name: str, model: type | None = None):
        return self._get_manager("blob", name, model)

    def log(self, name: str, model: type | None = None):
        return self._get_manager("log", name, model)

    def lock(self, name: str, timeout=None, lock_ttl=60.0, poll_interval=0.1):
        return self._get_manager("lock", name, timeout, lock_ttl, poll_interval)

    def sketch(self, name: str, capacity=1_000_000, error_rate=0.01, model=None):
        return self._get_manager("sketch", name, capacity, error_rate, model)

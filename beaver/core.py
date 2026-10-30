import asyncio
import json
import logging
from pathlib import Path
import threading
from typing import Any, Self, Type, AsyncContextManager

import aiosqlite
from pydantic import BaseModel

from .interfaces import (
    IBeaverBlob,
    IBeaverChannel,
    IBeaverDict,
    IBeaverDocuments,
    IBeaverEvents,
    IBeaverGraph,
    IBeaverList,
    IBeaverLock,
    IBeaverLog,
    IBeaverQueue,
    IBeaverSketch,
    IBeaverVectors,
)


from .blobs import AsyncBeaverBlob
from .bridge import BeaverBridge
from .cache import DummyCache
from .channels import AsyncBeaverChannel, PubSubEngine
from .dicts import AsyncBeaverDict
from .docs import AsyncBeaverDocuments
from .events import AsyncBeaverEvents
from .graphs import AsyncBeaverGraph
from .lists import AsyncBeaverList
from .locks import AsyncBeaverLock
from .logs import AsyncBeaverLog
from .manager import AsyncBeaverBase
from .queues import AsyncBeaverQueue
from .sketches import AsyncBeaverSketch
from .vectors import AsyncBeaverVectors


BEAVER_DB_VERSION = 1

_log = logging.getLogger("beaver")


class BeaverIncompatibleSchemaError(RuntimeError):
    """Raised when opening a database whose schema is incompatible with this
    version of beaver. The user must dump-and-reload to migrate.
    See docs/migration-rc3-to-rc4-lists.md."""


class BeaverLegacySchemaError(BeaverIncompatibleSchemaError):
    """Raised when opening a database written by beaver 1.x.

    1.x stored data in single-prefix tables (``beaver_dicts``, ``beaver_lists``,
    ...); 2.x uses dunder names (``__beaver_dicts__``, ...). Opening a 1.x file
    with 2.x would leave the legacy data invisible and start a parallel
    dataset beside it, so we refuse instead. See docs/migration-1x-to-2x.md."""


class BeaverIncompleteSchemaError(BeaverIncompatibleSchemaError):
    """Raised when a read-only database lacks required Beaver 2.x tables.

    Writable connections repair additive schema gaps during ``connect()``.
    A read-only inspector cannot do that safely, and presenting only the tables
    that happen to exist would make partial state look like valid empty data.
    """


#: Core table names written by beaver 1.x. Detection keys on these exact names
#: rather than a ``beaver_%`` prefix match so an unrelated user table in the
#: same file cannot trigger a false refusal. 2.x never creates any of them —
#: every ``CREATE TABLE`` in the package uses the dunder form.
LEGACY_1X_TABLES = frozenset(
    {
        "beaver_blobs",
        "beaver_collection_versions",
        "beaver_collections",
        "beaver_dicts",
        "beaver_edges",
        "beaver_fts_index",
        "beaver_lists",
        "beaver_lock_waiters",
        "beaver_logs",
        "beaver_manager_versions",
        "beaver_priority_queues",
        "beaver_pubsub_log",
        "beaver_sketches",
        "beaver_trigrams",
        "beaver_vector_change_log",
    }
)


# Every table created by the current additive schema. A writable connection can
# create a table introduced by a newer release; a read-only connection cannot,
# so it must refuse the partial view instead of reporting missing stores empty.
REQUIRED_2X_TABLES = frozenset(
    {
        "__beaver_blobs__",
        "__beaver_manager_versions__",
        "__beaver_dicts__",
        "__beaver_lists__",
        "__beaver_lock_waiters__",
        "__beaver_logs__",
        "__beaver_field_index__",
        "__beaver_field_index_manifest__",
        "__beaver_priority_queues__",
        "__beaver_pubsub_log__",
        "__beaver_sketches__",
        "__beaver_documents__",
        "__beaver_fts_index__",
        "__beaver_trigrams__",
        "__beaver_edges__",
        "__beaver_vectors__",
        "__beaver_lsh_config__",
        "__beaver_lsh_index__",
    }
)


class TransactionTimeoutError(TimeoutError):
    """Raised when a transaction could not take the write lock in time.

    beaver multiplexes every modality over a *single* connection, so tasks that
    want to write queue on an in-process lock and SQLite's busy-timeout — which
    only arbitrates between separate connections — never applies to them. The
    bound is `connection_timeout` (or the per-call `timeout=` on
    ``db.transaction()``).

    Seeing this means a writer is holding the transaction open longer than the
    budget: a long-running block, a stalled task, or a genuine write storm."""


class Transaction:
    """
    A Reentrant Async Context Manager for database transactions.

    If a task already holds the transaction lock (nested @atomic calls),
    this acts as a pass-through. The actual BEGIN/COMMIT only happens
    at the outermost level.
    """

    def __init__(self, db: "AsyncBeaverDB", *, timeout: float | None = None):
        self.db = db
        self._is_root = False
        self._timeout = db._timeout if timeout is None else timeout

    async def __aenter__(self):
        current_task = asyncio.current_task()

        # 1. Check Reentrancy: Do we already own the transaction?
        #    `is not None` matters: outside a task `current_task()` is None,
        #    and a bare `==` would read that as owning the transaction.
        if current_task is not None and self.db._tx_owner_task is current_task:
            self._is_root = False
            return self

        # 2. Acquire the write lock, bounded (see _acquire).
        await self._acquire()

        # 3. Start the DB transaction, THEN claim ownership.
        #
        #    Order matters. `__aexit__` never runs when `__aenter__` raises, so
        #    everything between the acquire above and the return below has to
        #    clean up after itself — and ownership must not name a transaction
        #    that never began, or the reentrancy check above waves this task's
        #    next transaction through as a no-op.
        #
        #    Using isolation_level=None globally means we MUST start manually.
        try:
            await self.db.connection.execute("BEGIN IMMEDIATE")
        except BaseException:
            self._clean_up_in_the_background()
            raise

        self.db._tx_owner_task = current_task
        self._is_root = True
        return self

    async def _acquire(self) -> None:
        """Take the write lock, waiting at most `self._timeout` seconds.

        The wait has to be bounded because beaver multiplexes every modality
        over a *single* connection: contending tasks queue here, on an
        in-process `asyncio.Lock`, and SQLite's busy-timeout — which only
        arbitrates between separate connections — never gets a say. An
        unbounded wait here is indistinguishable from a hang, and in WAL mode
        readers keep working throughout, so the process looks alive while every
        writer is stuck behind it.
        """
        if await self._steal_if_orphaned():
            return

        try:
            async with asyncio.timeout(self._timeout):
                await self.db._tx_lock.acquire()
        except TimeoutError:
            # A holder that finished without releasing may have appeared while
            # we waited; take it over rather than reporting contention.
            if await self._steal_if_orphaned():
                return
            raise TransactionTimeoutError(
                f"could not take the database write lock within "
                f"{self._timeout:g}s — another task is holding a transaction "
                f"open on {self.db._db_path!r}"
            ) from None

    async def _steal_if_orphaned(self) -> bool:
        """Take over a lock whose owner has already finished.

        A task that is `done()` cannot still be inside its `async with` body,
        so nobody is coming back to commit or release: waiting out the timeout
        would only delay an error. The rollback matters as much as the lock —
        the orphan's `BEGIN IMMEDIATE` is what pins the file for every *other*
        connection too, and SQLite refuses to begin a transaction inside one.

        Returns True when this call now holds the lock. The lock object stays
        `locked()` throughout; only ownership changes hands, so tasks already
        queued on it keep waiting instead of racing us for it.

        An owner of None means someone is mid-BEGIN and has not claimed the
        lock yet — that is live, not orphaned. Nothing else can be `done()` and
        still be running its transaction body, so there is no false positive
        here that would roll back somebody's in-flight work.
        """
        owner = self.db._tx_owner_task
        if owner is None or not owner.done() or not self.db._tx_lock.locked():
            return False

        # Loud, per beaver's rule about partial state: reclaiming is recovery
        # from a bug somewhere, not a normal event, and a silent recovery is
        # how the caller never learns it has a leak.
        _log.warning(
            "reclaiming an orphaned transaction on %r: its owning task (%s) "
            "finished without committing or rolling back",
            self.db._db_path,
            owner.get_name(),
        )
        self.db._tx_owner_task = None

        # Awaited, unlike the cleanup on the failure path below. There, the
        # release()/wake-up of the next waiter is itself scheduled *after* the
        # rollback task, so the queue order works out on its own. Here the same
        # coroutine goes straight on to BEGIN IMMEDIATE without yielding, so a
        # merely-scheduled rollback would land behind it — and SQLite refuses
        # to begin a transaction inside one.
        #
        # Bounded, because the orphan's own transaction did complete its BEGIN,
        # so the worker thread should be free; if it is not, something worse is
        # wrong and the caller deserves to hear about it rather than wait.
        try:
            async with asyncio.timeout(self._timeout):
                await self.db.connection.rollback()
        except TimeoutError:
            self.db._tx_lock.release()
            raise TransactionTimeoutError(
                f"could not roll back an orphaned transaction on "
                f"{self.db._db_path!r} within {self._timeout:g}s — the "
                f"connection is not responding"
            ) from None
        except Exception:
            pass  # nothing was open after all; the lock is ours either way
        return True

    def _clean_up_in_the_background(self) -> None:
        """Undo a BEGIN that failed, and release the lock once it is undone.

        A BEGIN can fail two ways, and they need opposite things:

        * **It raised.** Nothing began; the rollback is a formality.
        * **Its await was cancelled.** `connection.execute("BEGIN IMMEDIATE")`
          is two things — the statement running on aiosqlite's worker thread,
          and the future we wait on. Cancelling the wait does not un-run the
          statement, so SQLite's write lock may now be held with nothing left
          to release it. That is the whole outage this class exists to prevent.

        We cannot tell which happened, so we always roll back. What we must not
        do is **await** it here: the worker thread may be parked inside
        SQLite's busy handler because another *connection* holds the write
        lock, and aiosqlite serialises one queue onto that thread — so the
        rollback would sit behind the very statement that is stuck, turning a
        caller's 1.5 s deadline into a 30 s hang. (Measured: warden's /healthz
        sat through the full 10 s of curl's `--max-time` exactly this way.)

        So the caller leaves immediately and a background task finishes the
        job. **It holds `_tx_lock` until the rollback lands**, which is what
        makes the ordering safe: without that, an uncontended `Lock.acquire()`
        does not yield, so the very next transaction in this task would enqueue
        its BEGIN *ahead* of our pending ROLLBACK — and get rolled back by it.
        Mutual exclusion orders the two; scheduling luck does not. Anyone
        waiting meanwhile is bounded by `_acquire`, and a store this wedged
        genuinely is unavailable.
        """

        async def clean_up():
            try:
                await self.db.connection.rollback()
            except Exception as exc:
                # Expected when the BEGIN never took: there is no transaction
                # to undo. The caller already has its own exception.
                _log.debug("rollback of an abandoned transaction failed: %r", exc)
            finally:
                self.db._tx_lock.release()

        try:
            task = asyncio.ensure_future(clean_up())
        except RuntimeError:  # no running loop left to clean up on
            self.db._tx_lock.release()
            return
        # Hold a reference: a bare ensure_future() can be garbage-collected
        # mid-flight, and this one is holding the write lock.
        self.db._pending_rollbacks.add(task)
        task.add_done_callback(self.db._pending_rollbacks.discard)

    async def __aexit__(self, exc_type, exc, tb):
        # Only the root transaction performs the Commit/Rollback and Release
        if not self._is_root:
            return

        try:
            if exc_type:
                await self.db.connection.rollback()
            else:
                await self.db.connection.commit()
        finally:
            # Always clear ownership and release lock
            self.db._tx_owner_task = None
            self.db._tx_lock.release()


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
        read_only: bool = False,
        connection_timeout: float = 30.0,
        cache_timeout: float = 0.0,
        pragma_wal: bool = True,
        pragma_synchronous: bool = False,
        pragma_temp_memory: bool = True,
        pragma_mmap_size: int = 256 * 1024 * 1024,
    ):
        self._db_path = db_path
        self._read_only = read_only
        if read_only and db_path == ":memory:":
            raise ValueError("read-only databases must be existing files, not :memory:")
        # Bounds both ways a write can be made to wait: SQLite's busy-timeout
        # (contention from another *connection*) and the transaction lock below
        # (contention from another *task* on this one). Only the second one
        # applies in a single-process app, which is why it must be bounded too.
        self._timeout = connection_timeout
        self._cache_timeout = cache_timeout

        # The Single Source of Truth Connection
        self._connection: aiosqlite.Connection | None = None

        # Locking Primitives
        self._tx_lock = asyncio.Lock()
        self._tx_owner_task: asyncio.Task | None = None  # Track owner for reentrancy
        # In-flight cleanup rollbacks (see Transaction._rollback_quietly), held
        # only so the event loop cannot garbage-collect them mid-flight.
        self._pending_rollbacks: set[asyncio.Task] = set()

        # Manager Singleton Cache
        self._manager_cache: dict[tuple[type, str], Any] = {}

        # Store pragma settings
        self._pragma_wal = pragma_wal
        self._pragma_synchronous = pragma_synchronous
        self._pragma_temp_memory = pragma_temp_memory
        self._pragma_mmap_size = pragma_mmap_size

        # Pub/Sub Engine
        self._pubsub_engine: PubSubEngine | None = None

    async def pubsub_engine(self) -> PubSubEngine:
        if self._pubsub_engine is None:
            self._pubsub_engine = PubSubEngine(self)
            await self._pubsub_engine.start()

        return self._pubsub_engine

    async def connect(self) -> Self:
        """
        Initializes the async database connection and creates tables.
        Must be awaited before using the DB.
        """
        if self._connection is not None:
            return self

        database = self._db_path
        connect_kwargs: dict[str, Any] = {}
        if self._read_only:
            path = Path(self._db_path).expanduser()
            if not path.is_file():
                raise FileNotFoundError(
                    f"read-only Beaver database does not exist: {self._db_path!r}"
                )
            database = f"{path.resolve().as_uri()}?mode=ro"
            connect_kwargs["uri"] = True

        self._connection = await aiosqlite.connect(
            database,
            timeout=self._timeout,
            # We will manage transactions manually via .transaction()
            isolation_level=None,
            **connect_kwargs,
        )
        # If any setup step below fails (e.g. an incompatible-schema version
        # check), close the just-opened connection so we don't leak its
        # background aiosqlite thread.
        try:
            self._connection.row_factory = aiosqlite.Row

            if self._read_only:
                # Connection-local defense in depth. ``mode=ro`` is the actual
                # file-level guarantee; query_only also rejects writes to any
                # attached database without changing persistent file state.
                await self._connection.execute("PRAGMA query_only = ON")
                await self._check_version(allow_upgrade=False)
                await self._check_complete_schema()
                return self

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

            await self._check_version(allow_upgrade=True)
            await self._create_all_tables()
            await self._connection.execute(f"PRAGMA user_version = {BEAVER_DB_VERSION}")
        except BaseException:
            await self._connection.close()
            self._connection = None
            raise

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

    @property
    def read_only(self) -> bool:
        """Whether this connection was opened through SQLite's ``mode=ro``."""
        return self._read_only

    @property
    def path(self) -> str:
        """The database path supplied by the caller."""
        return self._db_path

    def transaction(self, *, timeout: float | None = None) -> AsyncContextManager:
        """
        Returns an async context manager for an atomic transaction.
        Use: async with db.transaction(): ...

        `timeout` bounds the wait for the write lock, defaulting to this
        database's `connection_timeout`. Pass a tighter one from a caller with
        its own latency budget — a healthcheck, a request handler — so a
        contended write fails fast with `TransactionTimeoutError` instead of
        holding the caller for the full default.
        """
        return Transaction(self, timeout=timeout)

    async def _tables_named(self, names) -> list[str]:
        """Return which of `names` exist as tables in the open database."""
        names = tuple(sorted(names))
        placeholders = ",".join("?" * len(names))
        cursor = await self._connection.execute(
            f"SELECT name FROM sqlite_master WHERE type = 'table' AND name IN ({placeholders})",
            names,
        )
        return sorted(row[0] for row in await cursor.fetchall())

    async def _modern_tables(self) -> list[str]:
        """Return the __beaver_*__ tables present. GLOB is used because `_` is
        a literal in GLOB patterns but a wildcard in LIKE."""
        cursor = await self._connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name GLOB '__beaver_*__'"
        )
        return sorted(row[0] for row in await cursor.fetchall())

    async def _check_complete_schema(self) -> None:
        """Refuse a partial current schema that read-only mode cannot repair."""
        present = set(await self._tables_named(REQUIRED_2X_TABLES))
        missing = sorted(REQUIRED_2X_TABLES - present)
        if missing:
            raise BeaverIncompleteSchemaError(
                f"Database {self._db_path!r} has an incomplete Beaver 2.x "
                "schema and cannot be opened read-only. Missing tables: "
                f"{', '.join(missing)}. Open it once in writable mode with "
                "this Beaver version to add compatible schema tables."
            )

    async def _legacy_version_label(self) -> str:
        """Read the version beaver 1.x stamped into beaver_dicts.__metadata__."""
        try:
            cursor = await self._connection.execute(
                "SELECT value FROM beaver_dicts "
                "WHERE dict_name = '__metadata__' AND key = 'version'"
            )
            row = await cursor.fetchone()
        except aiosqlite.Error:
            return "unknown"

        if row is None or row[0] is None:
            return "unknown"

        try:
            return str(json.loads(row[0]))
        except (TypeError, ValueError):
            return str(row[0])

    async def _check_legacy_schema(self) -> None:
        """Refuse databases written by beaver 1.x.

        1.x used single-prefix table names (`beaver_dicts`, `beaver_lists`, ...)
        where 2.x uses dunder names. Opening one here would silently report the
        database as empty and then write a second, parallel dataset beside the
        untouched legacy tables. See issues/41.

        Detection keys on the *presence* of legacy tables rather than the
        absence of dunder ones, because a brand-new database also has no dunder
        tables at this point — this runs before _create_all_tables.
        """
        legacy = await self._tables_named(LEGACY_1X_TABLES)
        if not legacy:
            return

        version = await self._legacy_version_label()
        modern = await self._modern_tables()
        listed = ", ".join(legacy)

        if modern:
            raise BeaverLegacySchemaError(
                f"Database {self._db_path!r} is SPLIT-BRAIN: it holds both a "
                f"beaver 1.x dataset and a beaver 2.x dataset side by side.\n"
                f"  legacy (beaver {version}) tables: {listed}\n"
                f"  2.x tables: {', '.join(modern)}\n"
                "A previous 2.x process opened this 1.x database without "
                "noticing, so reads returned empty and every subsequent write "
                "went into the 2.x tables. Both datasets are intact on disk, "
                "but they are disjoint: rolling back to beaver 1.x now loses "
                "everything written since that open, and continuing with 2.x "
                "leaves the original 1.x data unreachable.\n"
                "Do not write to this database again until it is reconciled. "
                "See docs/migration-1x-to-2x.md."
            )

        raise BeaverLegacySchemaError(
            f"Database {self._db_path!r} was created by beaver {version} and "
            "cannot be opened by beaver 2.x.\n"
            f"  legacy tables found: {listed}\n"
            "beaver 1.x stored data in single-prefix tables (beaver_dicts, "
            "beaver_lists, ...); 2.x uses dunder-prefixed tables "
            "(__beaver_dicts__, ...). Opening this file with 2.x would report "
            "every dict, list and collection as empty and then start a second, "
            "parallel dataset beside the original one.\n"
            "Your data is intact and untouched. Migrate it before reopening — "
            "see docs/migration-1x-to-2x.md."
        )

    async def _check_version(self, *, allow_upgrade: bool = True) -> None:
        """Verify the open database is compatible with this beaver version.

        Fresh databases have user_version=0; we accept that and stamp the
        current version after _create_all_tables runs. rc3-era databases also
        have user_version=0 but already have __beaver_lists__ with REAL
        item_order — we reject those unless the lists table is empty.
        """
        # Runs before the user_version fast path below: a split-brain database
        # has already been stamped to the current version by the accidental
        # 2.x open that created it, so the fast path would skip detection.
        await self._check_legacy_schema()

        cursor = await self._connection.execute("PRAGMA user_version")
        row = await cursor.fetchone()
        current = row[0] if row else 0

        if current == BEAVER_DB_VERSION:
            return

        if current > BEAVER_DB_VERSION:
            raise BeaverIncompatibleSchemaError(
                f"Database user_version is {current}; this beaver only "
                f"understands up to {BEAVER_DB_VERSION}. The database was "
                "written by a newer beaver release."
            )

        cursor = await self._connection.execute(
            "SELECT type FROM pragma_table_info('__beaver_lists__') WHERE name = 'item_order'"
        )
        row = await cursor.fetchone()
        if row is not None and row[0].upper() == "REAL":
            cursor = await self._connection.execute(
                "SELECT 1 FROM __beaver_lists__ LIMIT 1"
            )
            has_row = await cursor.fetchone()
            if has_row is not None:
                raise BeaverIncompatibleSchemaError(
                    "This database was created by beaver < 2.0rc4 and contains "
                    "persistent-list data using the old REAL ordering format. "
                    "rc4 changed __beaver_lists__.item_order from REAL to TEXT "
                    "(fractional indexing) and no automatic migration is "
                    "provided. See docs/migration-rc3-to-rc4-lists.md."
                )
            if not allow_upgrade:
                raise BeaverIncompatibleSchemaError(
                    "This database was created by beaver < 2.0rc4 and uses "
                    "the old REAL persistent-list ordering format. Its empty "
                    "lists table can be upgraded only by opening the database "
                    "in writable mode."
                )
            await self._connection.execute("DROP TABLE __beaver_lists__")

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

        # Lists
        await c.execute(
            """
            CREATE TABLE IF NOT EXISTS __beaver_lists__ (
                list_name TEXT NOT NULL,
                item_order TEXT NOT NULL,
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

        # Field Index (issue #42) — uniform per-field indexing.
        # Additive by design: new tables only, no ALTER, no version bump.
        await c.execute(
            """
            CREATE TABLE IF NOT EXISTS __beaver_field_index__ (
                kind      TEXT NOT NULL,
                name      TEXT NOT NULL,
                item_key  TEXT NOT NULL,
                field     TEXT NOT NULL,
                value     TEXT,
                value_num REAL,
                PRIMARY KEY (kind, name, item_key, field)
            )
        """
        )
        await c.execute(
            "CREATE INDEX IF NOT EXISTS idx_field_lookup "
            "ON __beaver_field_index__ (kind, name, field, value)"
        )
        await c.execute(
            "CREATE INDEX IF NOT EXISTS idx_field_lookup_num "
            "ON __beaver_field_index__ (kind, name, field, value_num)"
        )
        await c.execute(
            """
            CREATE TABLE IF NOT EXISTS __beaver_field_index_manifest__ (
                kind     TEXT NOT NULL,
                name     TEXT NOT NULL,
                field    TEXT NOT NULL,
                complete INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (kind, name, field)
            )
        """
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

        # Main Storage
        await c.execute(
            """
            CREATE TABLE IF NOT EXISTS __beaver_documents__ (
                collection TEXT NOT NULL,
                item_id TEXT NOT NULL,
                data TEXT NOT NULL,
                PRIMARY KEY (collection, item_id)
            )
        """
        )

        # FTS Index
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

        # Fuzzy Index (Trigrams)
        await c.execute(
            """
            CREATE TABLE IF NOT EXISTS __beaver_trigrams__ (
                collection TEXT NOT NULL,
                item_id TEXT NOT NULL,
                trigram TEXT NOT NULL,
                PRIMARY KEY (collection, item_id, trigram)
            )
        """
        )
        await c.execute(
            "CREATE INDEX IF NOT EXISTS idx_trigram_lookup ON __beaver_trigrams__ (collection, trigram)"
        )

        # Edges
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

        # Index for reverse lookups (parents)
        await c.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_edges_target
            ON __beaver_edges__ (collection, target_item_id)
        """
        )

        # Vectors (Main Store)
        await c.execute(
            """
            CREATE TABLE IF NOT EXISTS __beaver_vectors__ (
                collection TEXT NOT NULL,
                item_id TEXT NOT NULL,
                vector BLOB NOT NULL,
                metadata TEXT,
                PRIMARY KEY (collection, item_id)
            )
        """
        )

        # --- LSH Strategy Tables ---

        # LSH Config (Hyperplanes per collection)
        await c.execute(
            """
            CREATE TABLE IF NOT EXISTS __beaver_lsh_config__ (
                collection TEXT PRIMARY KEY,
                hyperplanes BLOB NOT NULL
            )
            """
        )

        # LSH Index (Maps buckets to item_ids)
        await c.execute(
            """
            CREATE TABLE IF NOT EXISTS __beaver_lsh_index__ (
                collection TEXT NOT NULL,
                bucket_id INTEGER NOT NULL,
                item_id TEXT NOT NULL,
                PRIMARY KEY (collection, bucket_id, item_id)
            )
            """
        )
        # Optimized index for retrieving items in a bucket
        await c.execute(
            "CREATE INDEX IF NOT EXISTS idx_lsh_lookup ON __beaver_lsh_index__ (collection, bucket_id)"
        )

        await self.connection.commit()

    def singleton[T: AsyncBeaverBase](self, cls: type[T], name, **kwargs) -> T:
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

    def dict[T: BaseModel](
        self, name: str, model: type[T] | None = None, secret: str | None = None
    ) -> AsyncBeaverDict[T]:
        return self.singleton(AsyncBeaverDict, name, model=model, secret=secret)

    def list[T: BaseModel](
        self, name: str, model: type[T] | None = None
    ) -> AsyncBeaverList[T]:
        return self.singleton(AsyncBeaverList, name, model=model)

    def queue[T: BaseModel](
        self, name: str, model: type[T] | None = None
    ) -> AsyncBeaverQueue[T]:
        return self.singleton(AsyncBeaverQueue, name, model=model)

    def docs[T: BaseModel](
        self, name: str, model: Type[T] | None = None
    ) -> AsyncBeaverDocuments[T]:
        return self.singleton(AsyncBeaverDocuments, name, model=model)

    def graphs[T: BaseModel](
        self, name: str, model: Type[T] | None = None
    ) -> AsyncBeaverGraph[T]:
        return self.singleton(AsyncBeaverGraph, name, model=model)

    def channel[T: BaseModel](
        self, name: str, model: type[T] | None = None
    ) -> AsyncBeaverChannel[T]:
        return self.singleton(AsyncBeaverChannel, name, model=model)

    def blob[T: BaseModel](
        self, name: str, model: type[T] | None = None
    ) -> AsyncBeaverBlob[T]:
        return self.singleton(AsyncBeaverBlob, name, model=model)

    def log[T: BaseModel](
        self,
        name: str,
        model: type[T] | None = None,
        # Quoted: inside a PEP 695 generic scope the class body is visible, so
        # a bare `list[str]` resolves to AsyncBeaverDB.list, not the builtin.
        indexed: "list[str] | None" = None,
    ) -> AsyncBeaverLog[T]:
        """Open a log.

        `indexed` declares the fields whose values are maintained in the field
        index. **Declare on first use:** `singleton()` keys its cache on
        `(cls, name)` only, so after a bare `db.log("audit")` a later
        `db.log("audit", indexed=[...])` returns the already-cached, undeclared
        manager and the declaration is silently dropped.
        """
        return self.singleton(AsyncBeaverLog, name, model=model, indexed=indexed)

    async def indexes(self) -> dict:
        """Every declared field index in this database, by (kind, name)."""
        from . import indexing

        return await indexing.all_field_indexes(self.connection)

    def lock(
        self, name: str, timeout=None, lock_ttl=60.0, poll_interval=0.1
    ) -> AsyncBeaverLock:
        return AsyncBeaverLock(self, name, timeout, lock_ttl, poll_interval)

    def sketch[T: BaseModel](
        self,
        name: str,
        capacity=1_000_000,
        error_rate=0.01,
        model: type[T] | None = None,
    ) -> AsyncBeaverSketch[T]:
        return self.singleton(
            AsyncBeaverSketch,
            name,
            capacity=capacity,
            error_rate=error_rate,
            model=model,
        )

    def graph[T: BaseModel](
        self, name, model: type[T] | None = None
    ) -> AsyncBeaverGraph[T]:
        return self.singleton(
            AsyncBeaverGraph,
            name,
            model=model,
        )

    def events[T: BaseModel](
        self, name, model: type[T] | None = None
    ) -> AsyncBeaverEvents:
        return self.singleton(
            AsyncBeaverEvents,
            name,
            model=model,
        )

    def vectors[T: BaseModel](
        self, name, model: type[T] | None = None
    ) -> AsyncBeaverVectors:
        return self.singleton(AsyncBeaverVectors, name, model=model)

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
        try:
            self._async_db = future.result()
        except BaseException:
            # connect() can legitimately fail (e.g. a legacy 1.x schema). Stop
            # the reactor thread we just started instead of leaking it.
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=1.0)
            self._closed = True
            raise
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

    def dict[T: BaseModel](
        self, name: str, model: type[T] | None = None, secret: str | None = None
    ) -> IBeaverDict[T]:
        return self._get_manager("dict", name, model, secret)

    def list[T: BaseModel](
        self, name: str, model: type[T] | None = None
    ) -> IBeaverList[T]:
        return self._get_manager("list", name, model)

    def queue[T: BaseModel](
        self, name: str, model: type[T] | None = None
    ) -> IBeaverQueue[T]:
        return self._get_manager("queue", name, model)

    def docs[T: BaseModel](
        self, name: str, model: Type[T] | None = None
    ) -> IBeaverDocuments[T]:
        return self._get_manager("docs", name, model)

    def graph[T: BaseModel](
        self, name: str, model: Type[T] | None = None
    ) -> IBeaverGraph[T]:
        return self._get_manager("graph", name, model)

    def vectors[T: BaseModel](
        self, name: str, model: type[T] | None = None
    ) -> IBeaverVectors[T]:
        return self._get_manager("vectors", name, model)

    def channel[T: BaseModel](
        self, name: str, model: type[T] | None = None
    ) -> IBeaverChannel[T]:
        return self._get_manager("channel", name, model)

    def blob[T: BaseModel](
        self, name: str, model: type[T] | None = None
    ) -> IBeaverBlob[T]:
        return self._get_manager("blob", name, model)

    def log[T: BaseModel](
        self, name: str, model: type[T] | None = None
    ) -> IBeaverLog[T]:
        return self._get_manager("log", name, model)

    def lock(
        self,
        name: str,
        timeout: float | None = None,
        ttl: float = 60.0,
        poll_interval: float = 0.1,
    ) -> IBeaverLock:
        return self._get_manager("lock", name, timeout, ttl, poll_interval)

    def sketch[T: BaseModel](
        self,
        name: str,
        capacity: int = 1_000_000,
        error_rate: float = 0.01,
        model: type[T] | None = None,
    ) -> IBeaverSketch[T]:
        return self._get_manager("sketch", name, capacity, error_rate, model)

    def events[T: BaseModel](
        self, name: str, model: type[T] | None = None
    ) -> IBeaverEvents[T]:
        return self._get_manager("events", name, model)

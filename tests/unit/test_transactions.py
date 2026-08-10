"""The transaction *enter* path: bounded, leak-free, honest about ownership.

Written against a real outage (AInBox, 2026-08-10). A request task inside a
FastAPI app was cancelled while it was starting a transaction. `BEGIN
IMMEDIATE` had already run on aiosqlite's worker thread, but the coroutine
awaiting it never returned, so nothing ever committed, rolled back, or released
`_tx_lock`. The database was in WAL mode: every reader kept working while every
writer queued behind an `asyncio.Lock` that no longer had an owner. The
appliance served its login page and answered its healthcheck for hours while
nobody could authenticate.

The four properties below are what makes that unreachable. Each one is written
so that removing the corresponding guard in `Transaction` makes it fail.
"""

import asyncio
import sqlite3

import pytest

from beaver import AsyncBeaverDB, TransactionTimeoutError

pytestmark = pytest.mark.unit


def write_lock_is_free(db_path: str, *, timeout: float = 0.5) -> bool:
    """Can a *separate* SQLite connection take the write lock?

    This is the substrate assertion. Beaver's own state (`_tx_lock`,
    `_tx_owner_task`) can look tidy while an orphaned `BEGIN IMMEDIATE` still
    pins the file for every other process — that asymmetry is exactly what made
    the outage invisible. Only another connection can answer this honestly.
    """
    conn = sqlite3.connect(db_path, timeout=timeout)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("ROLLBACK")
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        conn.close()


@pytest.fixture
async def db(tmp_path):
    """A file-backed database with a short timeout, so a bounded wait is quick
    to observe and an unbounded one still trips pytest's 30 s cap."""
    path = str(tmp_path / "tx.db")
    database = AsyncBeaverDB(path, connection_timeout=0.5)
    await database.connect()
    database.test_path = path  # convenience for the substrate probe
    try:
        yield database
    finally:
        await database.close()


def patch_begin(database: AsyncBeaverDB, hook):
    """Replace `connection.execute` so BEGIN IMMEDIATE goes through `hook`.

    Everything else passes straight through, so the rest of beaver keeps
    working while we manufacture a failure in the one statement under test.
    """
    real = database.connection.execute

    async def execute(sql, *args, **kwargs):
        if str(sql).strip().upper().startswith("BEGIN"):
            return await hook(real, sql, *args, **kwargs)
        return await real(sql, *args, **kwargs)

    database.connection.execute = execute
    return real


async def test_a_cancelled_begin_strands_neither_lock(db):
    """The regression. Cancel a task mid-BEGIN; both locks must come back.

    `hook` reproduces the production shape faithfully: the statement really
    runs (so SQLite's write lock is really taken), and only then does the
    coroutine hang at an await where cancellation can land. Cancelling the wait
    does not un-run the statement.
    """
    began = asyncio.Event()

    async def hook(real, sql, *args, **kwargs):
        cursor = await real(sql, *args, **kwargs)
        began.set()
        await asyncio.sleep(3600)  # the await that never returns
        return cursor

    patch_begin(db, hook)

    async def victim():
        async with db.transaction():
            pass  # never reached — cancellation lands inside __aenter__

    task = asyncio.create_task(victim())
    await asyncio.wait_for(began.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # SQLite's write lock: released, or every other process stays blocked.
    assert write_lock_is_free(db.test_path)
    # Beaver's own lock: released, or every other task in this process does.
    assert not db._tx_lock.locked()
    assert db._tx_owner_task is None


async def test_a_cancelled_begin_leaves_the_next_writer_unblocked(db):
    """The symptom the users actually saw: the *next* write hangs forever."""
    began = asyncio.Event()

    async def hook(real, sql, *args, **kwargs):
        cursor = await real(sql, *args, **kwargs)
        began.set()
        await asyncio.sleep(3600)
        return cursor

    real = patch_begin(db, hook)

    async def victim():
        async with db.transaction():
            pass

    task = asyncio.create_task(victim())
    await asyncio.wait_for(began.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    db.connection.execute = real  # let the next BEGIN through normally
    async with asyncio.timeout(5):
        await db.dict("d").set("k", "written")
    assert await db.dict("d").fetch("k") == "written"


async def test_a_failing_begin_does_not_leave_a_phantom_owner(db):
    """Ownership is claimed only by a transaction that genuinely began.

    Marking ownership *before* `BEGIN IMMEDIATE` means a raising BEGIN leaves
    `_tx_owner_task` pointing at a transaction that never started — and the
    reentrancy check then waves the same task's next transaction through as a
    no-op. The assertion is behavioural: a rolled-back block must not persist,
    which it silently would if the block were a pass-through.
    """

    async def hook(real, sql, *args, **kwargs):
        raise sqlite3.OperationalError("disk I/O error")

    real = patch_begin(db, hook)

    with pytest.raises(sqlite3.OperationalError):
        async with db.transaction():
            pass

    assert db._tx_owner_task is None
    assert not db._tx_lock.locked()

    db.connection.execute = real
    with pytest.raises(RuntimeError):
        async with db.transaction():
            await db.dict("d").set("k", "should not survive")
            raise RuntimeError("boom")
    assert await db.dict("d").fetch("k", default=None) is None


async def test_waiting_for_the_write_lock_is_bounded(db):
    """A contended write gives up and says so, instead of waiting forever.

    beaver multiplexes one connection, so contending tasks queue on `_tx_lock`
    and SQLite's busy-timeout — which only arbitrates *between* connections —
    never gets a say. `connection_timeout` is the bound for both.
    """
    holder_entered = asyncio.Event()
    release = asyncio.Event()

    async def holder():
        async with db.transaction():
            holder_entered.set()
            await release.wait()

    task = asyncio.create_task(holder())
    await asyncio.wait_for(holder_entered.wait(), timeout=5)

    loop = asyncio.get_running_loop()
    started = loop.time()
    with pytest.raises(TransactionTimeoutError) as excinfo:
        async with db.transaction():
            pass
    waited = loop.time() - started

    assert 0.4 <= waited < 5, f"waited {waited:.3f}s, expected ~0.5s"
    # The message has to name the problem: this exception is what a caller sees
    # instead of a hang, and "TimeoutError" alone sends them hunting the network.
    assert "write lock" in str(excinfo.value)

    release.set()
    await task


async def test_the_per_transaction_timeout_overrides_the_default(db):
    """A caller on a latency budget (a healthcheck, a request handler) can ask
    for a tighter bound than the database's default."""
    holder_entered = asyncio.Event()
    release = asyncio.Event()

    async def holder():
        async with db.transaction():
            holder_entered.set()
            await release.wait()

    task = asyncio.create_task(holder())
    await asyncio.wait_for(holder_entered.wait(), timeout=5)

    loop = asyncio.get_running_loop()
    started = loop.time()
    with pytest.raises(TransactionTimeoutError):
        async with db.transaction(timeout=0.1):
            pass
    assert loop.time() - started < 0.4

    release.set()
    await task


async def test_an_orphaned_transaction_is_reclaimed_rather_than_waited_on(db):
    """A lock held by a task that has already finished is not contention.

    Nobody is coming back to commit it, so waiting out the timeout only delays
    the inevitable error. The owner is tracked, so the orphan is detectable:
    roll it back and take over.
    """

    async def leaker():
        # Enter without ever exiting — the shape of any future leak on this
        # path, whatever manufactures it.
        await db.transaction().__aenter__()

    task = asyncio.create_task(leaker())
    await task
    assert db._tx_lock.locked()
    assert task.done()

    loop = asyncio.get_running_loop()
    started = loop.time()
    async with db.transaction():
        await db.dict("d").set("k", "reclaimed")
    waited = loop.time() - started

    # Under the 0.5 s default this would have been a TransactionTimeoutError.
    assert waited < 0.4, f"waited {waited:.3f}s — that is a timeout, not a reclaim"
    assert await db.dict("d").fetch("k") == "reclaimed"
    assert write_lock_is_free(db.test_path)


async def test_a_live_holder_is_never_mistaken_for_an_orphan(db):
    """The reclaim must not steal a transaction that is still running.

    This is the dangerous half of the previous test: a false positive rolls
    back somebody's in-flight work. A task that is merely *slow* is not done.
    """
    holder_entered = asyncio.Event()
    release = asyncio.Event()
    committed = asyncio.Event()

    async def holder():
        async with db.transaction():
            holder_entered.set()
            await db.dict("d").set("k", "holder's write")
            await release.wait()
        committed.set()

    task = asyncio.create_task(holder())
    await asyncio.wait_for(holder_entered.wait(), timeout=5)

    with pytest.raises(TransactionTimeoutError):
        async with db.transaction(timeout=0.1):
            pass

    release.set()
    await task
    assert committed.is_set()
    assert await db.dict("d").fetch("k") == "holder's write"


async def test_nested_transactions_still_pass_through(db):
    """Reentrancy is the reason the owner is tracked at all — keep it working."""
    async with db.transaction() as outer:
        assert outer._is_root
        async with db.transaction() as inner:
            assert not inner._is_root
            await db.dict("d").set("k", "nested")
        # Still inside the root: the inner exit must not have committed.
        assert db._tx_owner_task is asyncio.current_task()
    assert await db.dict("d").fetch("k") == "nested"
    assert db._tx_owner_task is None
    assert not db._tx_lock.locked()

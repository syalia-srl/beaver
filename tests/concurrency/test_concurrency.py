"""Multi-process concurrency tests.

These run real `multiprocessing` workers against a shared file-backed DB to
prove the load-bearing claims of beaver's async-first + portal architecture:

  1. AsyncBeaverLock provides true mutual exclusion across processes.
  2. List push under contention does not lose writes.
  3. A reader process sees a writer's appends without torn rows.
  4. `.batched()` writes are invisible to other processes until the batch
     commits (transactional isolation).

We use the `spawn` start method so each worker boots a fresh interpreter and
its own `aiosqlite` connection — `fork` would inherit the parent's asyncio
loop and produce undefined behavior.

Workers are top-level functions (not test-local closures) so they're
picklable for `spawn`. Each takes a `db_path` and returns/exits cleanly.
"""

import asyncio
import multiprocessing
import time

import pytest

from beaver import AsyncBeaverDB, BeaverDB

pytestmark = pytest.mark.concurrency

MP = multiprocessing.get_context("spawn")


# --- Workers (must be top-level, picklable, no test-local closures) ---


def _worker_lock_increment(db_path: str, iterations: int) -> int:
    """Acquire a named lock, increment a counter in a dict, release. Repeat."""

    async def run():
        db = AsyncBeaverDB(db_path)
        await db.connect()
        try:
            counter = db.dict("counter")
            lock = db.lock("counter_lock", timeout=30.0, lock_ttl=10.0)
            done = 0
            for _ in range(iterations):
                async with lock:
                    current = await counter.fetch("n", default=0)
                    await counter.set("n", current + 1)
                    done += 1
            return done
        finally:
            await db.close()

    return asyncio.run(run())


def _worker_list_push(db_path: str, label: str, count: int) -> None:
    async def run():
        db = AsyncBeaverDB(db_path)
        await db.connect()
        try:
            lst = db.list("items")
            for i in range(count):
                await lst.push(f"{label}-{i}")
        finally:
            await db.close()

    asyncio.run(run())


def _worker_log_writer(db_path: str, count: int, sleep_per: float) -> None:
    async def run():
        db = AsyncBeaverDB(db_path)
        await db.connect()
        try:
            log = db.log("events")
            for i in range(count):
                await log.log({"i": i})
                if sleep_per:
                    await asyncio.sleep(sleep_per)
        finally:
            await db.close()

    asyncio.run(run())


def _worker_log_reader(db_path: str, target_count: int, deadline_s: float) -> int:
    """Poll the log until target_count entries are visible or deadline hits.

    Returns the number of entries observed; the test asserts on completeness.
    """

    async def run():
        db = AsyncBeaverDB(db_path)
        await db.connect()
        try:
            log = db.log("events")
            deadline = time.time() + deadline_s
            seen = 0
            while time.time() < deadline:
                entries = await log.range()
                # Verify monotonicity on every poll — torn / out-of-order rows
                # would surface here, not just at the end.
                timestamps = [e.timestamp for e in entries]
                assert timestamps == sorted(timestamps), "non-monotonic timestamps"
                # Every entry's payload must round-trip cleanly (no partial JSON).
                for e in entries:
                    assert isinstance(e.data, dict) and "i" in e.data
                seen = len(entries)
                if seen >= target_count:
                    return seen
                await asyncio.sleep(0.05)
            return seen
        finally:
            await db.close()

    return asyncio.run(run())


def _worker_batched_writer(db_path: str, count: int, hold_s: float) -> None:
    """Open a batch, buffer `count` items, sleep `hold_s` *before* exiting.

    The sleep happens inside the batch but *before* `__aexit__`, so the
    writes are still pending. Sibling readers should see count == 0 during
    the sleep.
    """

    async def run():
        db = AsyncBeaverDB(db_path)
        await db.connect()
        try:
            d = db.dict("batched_isolation")
            async with d.batched() as batch:
                for i in range(count):
                    batch.set(f"k_{i}", i)
                # Hold the batch open without flushing — exercise isolation.
                await asyncio.sleep(hold_s)
        finally:
            await db.close()

    asyncio.run(run())


def _worker_count_dict(db_path: str, name: str) -> int:
    async def run():
        db = AsyncBeaverDB(db_path)
        await db.connect()
        try:
            return await db.dict(name).count()
        finally:
            await db.close()

    return asyncio.run(run())


# --- Tests ---


def test_lock_provides_cross_process_mutual_exclusion(shared_db_path):
    """N workers race to increment a shared counter. With proper locking,
    every increment lands and the final value equals N * iterations.

    Without locking, a read-modify-write race would cause lost updates and
    the final value would be < N * iterations.
    """
    n_workers = 4
    iterations = 25
    expected = n_workers * iterations

    # Pre-create the DB file so all workers see the same schema
    with BeaverDB(shared_db_path) as db:
        db.dict("counter")["n"] = 0  # seed

    with MP.Pool(n_workers) as pool:
        results = pool.starmap(
            _worker_lock_increment,
            [(shared_db_path, iterations)] * n_workers,
        )

    assert sum(results) == expected, "workers reported partial completion"

    # Verify final counter value from a fresh process
    with BeaverDB(shared_db_path) as db:
        assert db.dict("counter")["n"] == expected, "lost updates → lock failed"


def test_concurrent_list_push_loses_no_writes(shared_db_path):
    """Each worker pushes items with a unique label prefix. Final list must
    contain every item from every worker — no torn rows, no lost pushes.

    The list manager's `@atomic` decorator + the manager's internal lock are
    what we're proving here.
    """
    n_workers = 4
    per_worker = 50
    expected_total = n_workers * per_worker

    with BeaverDB(shared_db_path) as db:
        db.list("items")  # init schema

    procs = [
        MP.Process(target=_worker_list_push, args=(shared_db_path, f"w{i}", per_worker))
        for i in range(n_workers)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=30)
        assert p.exitcode == 0, f"worker failed with exitcode {p.exitcode}"

    with BeaverDB(shared_db_path) as db:
        items = list(db.list("items"))

    assert len(items) == expected_total
    # Every (label, index) tuple appears exactly once
    seen = set(items)
    assert len(seen) == expected_total, "duplicate items found"
    for i in range(n_workers):
        for j in range(per_worker):
            assert f"w{i}-{j}" in seen, f"missing item w{i}-{j}"


def test_log_reader_sees_writer_appends_in_order(shared_db_path):
    """A writer process appends 200 entries; a reader process polls and
    confirms it sees the full set with monotonically-increasing timestamps
    and no torn rows.
    """
    target = 200

    with BeaverDB(shared_db_path) as db:
        db.log("events")  # init schema

    writer = MP.Process(target=_worker_log_writer, args=(shared_db_path, target, 0.001))
    writer.start()

    # Reader runs in this process via the worker function (still spawns
    # its own AsyncBeaverDB connection so this is a real cross-connection
    # read, not a same-instance shortcut).
    seen = _worker_log_reader(shared_db_path, target, deadline_s=15.0)

    writer.join(timeout=15)
    assert writer.exitcode == 0, f"writer failed: {writer.exitcode}"
    assert seen == target, f"reader saw {seen}/{target} entries"


def test_batched_writes_invisible_until_commit(shared_db_path):
    """Process A holds an open `.batched()` block with 100 buffered writes
    for ~0.4s before flushing. While A is holding, sibling reads must see
    count == 0; after A commits, count must be 100.

    This proves SQL transaction isolation across processes — the buffered
    inserts don't leak out of A's transaction.
    """
    count = 100
    hold = 0.4

    with BeaverDB(shared_db_path) as db:
        db.dict("batched_isolation")  # init

    writer = MP.Process(
        target=_worker_batched_writer, args=(shared_db_path, count, hold)
    )
    writer.start()

    # Give the writer a beat to enter the batch
    time.sleep(0.15)

    # Mid-flight read: nothing visible yet
    mid_count = _worker_count_dict(shared_db_path, "batched_isolation")
    assert mid_count == 0, f"isolation breached: saw {mid_count} pending writes"

    writer.join(timeout=10)
    assert writer.exitcode == 0

    # After commit: all writes visible
    final_count = _worker_count_dict(shared_db_path, "batched_isolation")
    assert final_count == count

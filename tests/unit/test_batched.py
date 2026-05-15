"""Tests for the .batched() bulk-write API across managers (issue #27)."""

import pytest

from beaver import AsyncBeaverDB


class _ExecManyCounter:
    """Spy that wraps connection.executemany to count bulk-insert calls.

    The load-bearing assertion for `.batched()` is that the buffered writes
    flush as one (or a small constant number of) `executemany` calls, not
    N individual `execute` calls. Counting bulk calls here proves the batch
    really did bulk-insert, regardless of how many internal lock transactions
    the manager opens around it.
    """

    def __init__(self, conn):
        self._conn = conn
        self._original = conn.executemany
        self.calls = 0
        conn.executemany = self._spy

    def _spy(self, sql, *args, **kwargs):
        self.calls += 1
        return self._original(sql, *args, **kwargs)

    def restore(self):
        self._conn.executemany = self._original


# --- Dict ---


async def test_dict_batched_bulk_insert(async_db_mem: AsyncBeaverDB):
    d = async_db_mem.dict("bulk")

    counter = _ExecManyCounter(async_db_mem.connection)
    try:
        async with d.batched() as batch:
            for i in range(1000):
                batch.set(f"k_{i}", i)
    finally:
        counter.restore()

    # Single executemany flush for 1000 inserts (not 1000 individual execute calls)
    assert counter.calls == 1, f"expected 1 executemany, got {counter.calls}"
    assert await d.count() == 1000
    assert await d.get("k_0") == 0
    assert await d.get("k_999") == 999


async def test_dict_batched_setitem_syntax(async_db_mem: AsyncBeaverDB):
    """batch[key] = value must work alongside batch.set(...)."""
    d = async_db_mem.dict("syntax")

    async with d.batched() as batch:
        batch["a"] = 1
        batch["b"] = 2
        batch.set("c", 3, ttl_seconds=60)

    assert await d.count() == 3
    assert await d.get("a") == 1
    assert await d.get("b") == 2
    assert await d.get("c") == 3


async def test_dict_batched_empty_no_op(async_db_mem: AsyncBeaverDB):
    """Exiting an empty batch must not error or write."""
    d = async_db_mem.dict("empty")

    async with d.batched() as batch:
        pass

    assert await d.count() == 0


async def test_dict_batched_rollback_on_error(async_db_mem: AsyncBeaverDB):
    """If the body raises, no items should be persisted."""
    d = async_db_mem.dict("rollback")
    await d.set("seed", "before")

    with pytest.raises(RuntimeError):
        async with d.batched() as batch:
            batch.set("k1", "v1")
            batch.set("k2", "v2")
            raise RuntimeError("boom")

    # Pre-existing seed survives; pending writes never landed
    assert await d.count() == 1
    assert await d.get("seed") == "before"


# --- Log ---


async def test_log_batched_bulk_insert(async_db_mem: AsyncBeaverDB):
    log = async_db_mem.log("metrics")

    counter = _ExecManyCounter(async_db_mem.connection)
    try:
        async with log.batched() as batch:
            for i in range(1000):
                batch.log({"i": i})
    finally:
        counter.restore()

    assert counter.calls == 1
    assert await log.count() == 1000


async def test_log_batched_monotonic_timestamps(async_db_mem: AsyncBeaverDB):
    """All timestamps in the batch must be strictly increasing (no PK collisions)."""
    log = async_db_mem.log("dense")

    async with log.batched() as batch:
        for i in range(500):
            batch.log({"i": i})

    entries = await log.range()
    assert len(entries) == 500
    timestamps = [e.timestamp for e in entries]
    assert timestamps == sorted(timestamps)
    assert len(set(timestamps)) == 500  # all unique


# --- Blob ---


async def test_blob_batched_bulk_insert(async_db_mem: AsyncBeaverDB):
    blobs = async_db_mem.blob("icons")

    counter = _ExecManyCounter(async_db_mem.connection)
    try:
        async with blobs.batched() as batch:
            for i in range(200):
                batch.put(f"icon_{i}.png", f"data_{i}".encode(), metadata={"i": i})
    finally:
        counter.restore()

    assert counter.calls == 1
    assert await blobs.count() == 200
    item = await blobs.fetch("icon_42.png")
    assert item.data == b"data_42"
    assert item.metadata == {"i": 42}


# --- Docs ---


async def test_docs_batched_bulk_insert(async_db_mem: AsyncBeaverDB):
    docs = async_db_mem.docs("articles")

    counter = _ExecManyCounter(async_db_mem.connection)
    try:
        async with docs.batched() as batch:
            for i in range(100):
                batch.index(body={"title": f"Article {i}", "tag": "news"})
    finally:
        counter.restore()

    # docs flushes a small constant number of executemany calls regardless of
    # batch size (documents insert + fts delete/insert + trigram delete[/insert]).
    # The contract is "small constant", not 1 — proves no per-doc round trips.
    assert counter.calls <= 5, f"expected ≤5 bulk flushes, got {counter.calls}"
    assert counter.calls >= 1
    assert await docs.count() == 100

    # FTS still indexed
    results = await docs.search("Article 5")
    assert len(results) >= 1


async def test_docs_batched_with_explicit_ids(async_db_mem: AsyncBeaverDB):
    """index(id=..., body=...) inside the batch must work."""
    docs = async_db_mem.docs("with_ids")

    async with docs.batched() as batch:
        batch.index(id="alpha", body={"title": "Alpha"})
        batch.index(id="beta", body={"title": "Beta"})

    alpha = await docs.get("alpha")
    assert alpha.body["title"] == "Alpha"


# --- List ---


async def test_list_batched_bulk_push(async_db_mem: AsyncBeaverDB):
    lst = async_db_mem.list("queue")

    counter = _ExecManyCounter(async_db_mem.connection)
    try:
        async with lst.batched() as batch:
            for i in range(500):
                batch.push(f"item_{i}")
    finally:
        counter.restore()

    assert counter.calls == 1
    assert await lst.count() == 500
    # Order preserved
    first = await lst.get(0)
    last = await lst.get(499)
    assert first == "item_0"
    assert last == "item_499"


async def test_list_batched_push_and_prepend(async_db_mem: AsyncBeaverDB):
    """Pushes go to the end, prepends to the beginning, both in one transaction."""
    lst = async_db_mem.list("mixed")
    await lst.push("middle")  # seed

    async with lst.batched() as batch:
        batch.push("after_1")
        batch.push("after_2")
        batch.prepend("before_1")
        batch.prepend("before_2")

    items = [item async for item in lst]
    # before_2 prepended last → at the very front
    assert items == ["before_2", "before_1", "middle", "after_1", "after_2"]


async def test_list_batched_insert_disallowed(async_db_mem: AsyncBeaverDB):
    """Per #27 §5, batch.insert(i, val) is not supported."""
    lst = async_db_mem.list("no_insert")

    async with lst.batched() as batch:
        with pytest.raises((AttributeError, NotImplementedError)):
            batch.insert(0, "x")


# --- Sync facade (Bridge) ---


def test_dict_batched_sync_facade(db_mem):
    """Sync usage via BeaverBridge: with db.dict('x').batched() as b: ..."""
    d = db_mem.dict("sync_bulk")

    with d.batched() as batch:
        for i in range(100):
            batch.set(f"k_{i}", i)

    assert len(d) == 100
    assert d["k_0"] == 0
    assert d["k_99"] == 99

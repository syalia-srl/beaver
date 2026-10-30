"""Regressions fixed in 2.4.2: lock order, FTS deletes, and reads that write."""

import time

import pytest

from beaver import AsyncBeaverDB
from beaver.docs import Document
from beaver.locks import AsyncBeaverLock

pytestmark = pytest.mark.unit


@pytest.fixture
async def db(tmp_path):
    database = AsyncBeaverDB(str(tmp_path / "t.db"))
    await database.connect()
    yield database
    await database.close()


async def test_a_later_insert_cannot_jump_ahead_of_the_holder(db, monkeypatch):
    """#38: a waiter that stamped first but inserted second must wait."""
    now = time.time()
    holder = AsyncBeaverLock(db, "registry")
    assert await holder.acquire()

    monkeypatch.setattr("beaver.locks.time.time", lambda: now - 5)
    late = AsyncBeaverLock(db, "registry")
    assert not await late.acquire(block=False)
    await holder.release()


async def _fts_ids(db):
    cursor = await db.connection.execute(
        "SELECT item_id FROM __beaver_fts_index__ ORDER BY item_id"
    )
    return [row[0] for row in await cursor.fetchall()]


@pytest.mark.parametrize(
    "doc_id", ["plain", "a-b c", 'q"uote', "日本語", "___", "!!!", "item_id:x", "OR"]
)
async def test_reindex_replaces_fts_rows_for_any_id(db, doc_id):
    docs = db.docs("c")
    await docs.index(Document(id=doc_id, body="first version"))
    await docs.index(Document(id=doc_id, body="second version"))
    assert await _fts_ids(db) == [doc_id]
    assert [r.document.id for r in await docs.search("second")] == [doc_id]
    assert await docs.search("first") == []


async def test_delete_does_not_touch_ids_that_tokenize_alike(db):
    """Porter stems `running` and `run` alike, and `a-b` and `a b` tokenize alike."""
    docs = db.docs("c")
    for doc_id in ("running", "run", "a-b", "a b"):
        await docs.index(Document(id=doc_id, body="text"))
    await docs.index(Document(id="running", body="other"))
    await docs.drop("a-b")
    assert await _fts_ids(db) == ["a b", "run", "running"]


async def test_delete_stays_in_its_collection(db):
    await db.docs("one").index(Document(id="same", body="text"))
    await db.docs("two").index(Document(id="same", body="text"))
    await db.docs("one").drop("same")
    assert await _fts_ids(db) == ["same"]
    assert len(await db.docs("two").search("text")) == 1


async def test_batched_reindex_replaces_fts_rows(db):
    docs = db.docs("c")
    async with docs.batched() as batch:
        batch.index(Document(id="a-b", body="first version"))
    async with docs.batched() as batch:
        batch.index(Document(id="a-b", body="second version"))
    assert await _fts_ids(db) == ["a-b"]
    assert await docs.search("first") == []


async def test_batched_index_is_not_quadratic(db):
    """#40: the second batch used to take 80 times as long as the first."""
    docs = db.docs("c")

    async def timed_batch(start):
        began = time.perf_counter()
        async with docs.batched() as batch:
            for i in range(start, start + 2000):
                batch.index(Document(id=f"d{i}", body=f"message number {i}"))
        return time.perf_counter() - began

    first = await timed_batch(0)
    second = await timed_batch(2000)
    assert second < max(first * 10, 1.0)


@pytest.mark.parametrize(
    "read",
    [
        lambda db: db.dict("x").fetch("k"),
        lambda db: db.dict("x").contains("k"),
        lambda db: db.docs("x").get("missing"),
    ],
)
async def test_a_read_writes_no_lock_row(db, read):
    await db.dict("x").set("k", {"v": 1})
    changes = db.connection.total_changes
    try:
        await read(db)
    except KeyError:
        pass
    assert db.connection.total_changes == changes


async def test_an_expired_key_is_still_removed_on_read(db):
    d = db.dict("x")
    await d.set("k", {"v": 1}, ttl_seconds=0.01)
    time.sleep(0.02)
    with pytest.raises(KeyError):
        await d.get("k")
    cursor = await db.connection.execute("SELECT count(*) FROM __beaver_dicts__")
    assert (await cursor.fetchone())[0] == 0

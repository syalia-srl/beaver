import httpx
import pytest
from httpx import ASGITransport

from beaver.server import create_app
from beaver.core import AsyncBeaverDB
from beaver.client import AsyncBeaverClient


@pytest.fixture
async def setup(tmp_path):
    db = AsyncBeaverDB(str(tmp_path / "test.db"))
    await db.connect()
    app = create_app(db)
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    client = AsyncBeaverClient.__new__(AsyncBeaverClient)
    client._http = httpx.AsyncClient(transport=transport, base_url="http://test")
    yield db, client
    await client.close()
    await db.close()


@pytest.mark.asyncio
async def test_put_then_peek(setup):
    db, client = setup
    q = client.queue("u")
    await q.put({"task": "a"}, priority=1.0)
    peeked = await q.peek()
    assert peeked["data"] == {"task": "a"}
    assert peeked["priority"] == 1.0
    assert await q.count() == 1  # peek doesn't remove


@pytest.mark.asyncio
async def test_put_then_get_pops_highest_priority(setup):
    db, client = setup
    q = client.queue("u")
    await q.put({"task": "low"}, priority=10.0)
    await q.put({"task": "high"}, priority=1.0)
    item = await q.get(block=False)
    assert item["data"] == {"task": "high"}
    assert await q.count() == 1


@pytest.mark.asyncio
async def test_peek_empty_returns_none(setup):
    db, client = setup
    q = client.queue("u")
    assert await q.peek() is None


@pytest.mark.asyncio
async def test_clear(setup):
    db, client = setup
    q = client.queue("u")
    await q.put({"task": "a"}, priority=1.0)
    await q.put({"task": "b"}, priority=2.0)
    await q.clear()
    assert await q.count() == 0

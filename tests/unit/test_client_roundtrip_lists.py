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
async def test_push_count_get(setup):
    db, client = setup
    lst = client.list("u")
    await lst.push({"v": 1})
    await lst.push({"v": 2})
    assert await lst.count() == 2
    assert await lst.get(0) == {"v": 1}
    assert await lst.get(1) == {"v": 2}


@pytest.mark.asyncio
async def test_prepend_then_get_at_zero(setup):
    db, client = setup
    lst = client.list("u")
    await lst.push({"v": 2})
    await lst.prepend({"v": 1})
    assert await lst.get(0) == {"v": 1}
    assert await lst.get(1) == {"v": 2}


@pytest.mark.asyncio
async def test_set_then_get(setup):
    db, client = setup
    lst = client.list("u")
    await lst.push({"v": 1})
    await lst.set(0, {"v": 99})
    assert await lst.get(0) == {"v": 99}


@pytest.mark.asyncio
async def test_delete_then_count(setup):
    db, client = setup
    lst = client.list("u")
    await lst.push({"v": 1})
    await lst.push({"v": 2})
    await lst.delete(0)
    assert await lst.count() == 1
    assert await lst.get(0) == {"v": 2}


@pytest.mark.asyncio
async def test_insert_middle(setup):
    db, client = setup
    lst = client.list("u")
    await lst.push({"v": 1})
    await lst.push({"v": 3})
    await lst.insert(1, {"v": 2})
    assert await lst.get(0) == {"v": 1}
    assert await lst.get(1) == {"v": 2}
    assert await lst.get(2) == {"v": 3}


@pytest.mark.asyncio
async def test_contains(setup):
    db, client = setup
    lst = client.list("u")
    await lst.push({"v": 1})
    assert await lst.contains({"v": 1}) is True
    assert await lst.contains({"v": 99}) is False


@pytest.mark.asyncio
async def test_pop_returns_last(setup):
    db, client = setup
    lst = client.list("u")
    await lst.push({"v": 1})
    await lst.push({"v": 2})
    popped = await lst.pop()
    assert popped == {"v": 2}
    assert await lst.count() == 1


@pytest.mark.asyncio
async def test_deque_returns_first(setup):
    db, client = setup
    lst = client.list("u")
    await lst.push({"v": 1})
    await lst.push({"v": 2})
    dequed = await lst.deque()
    assert dequed == {"v": 1}
    assert await lst.count() == 1


@pytest.mark.asyncio
async def test_clear(setup):
    db, client = setup
    lst = client.list("u")
    await lst.push({"v": 1})
    await lst.push({"v": 2})
    await lst.clear()
    assert await lst.count() == 0

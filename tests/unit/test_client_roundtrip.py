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
async def test_set_then_get(setup):
    db, client = setup
    d = client.dict("u")
    await d.set("alice", {"name": "Alice", "age": 30})
    result = await d.get("alice")
    assert result == {"name": "Alice", "age": 30}


@pytest.mark.asyncio
async def test_get_missing_raises_keyerror(setup):
    db, client = setup
    d = client.dict("u")
    with pytest.raises(KeyError):
        await d.get("missing")


@pytest.mark.asyncio
async def test_contains_then_delete_then_count(setup):
    db, client = setup
    d = client.dict("u")
    await d.set("a", {"v": 1})
    await d.set("b", {"v": 2})
    assert await d.contains("a") is True
    assert await d.count() == 2
    await d.delete("a")
    assert await d.contains("a") is False
    assert await d.count() == 1


@pytest.mark.asyncio
async def test_fetch_returns_default(setup):
    db, client = setup
    d = client.dict("u")
    result = await d.fetch("missing", default={"v": "fallback"})
    assert result == {"v": "fallback"}


@pytest.mark.asyncio
async def test_pop_then_get_missing(setup):
    db, client = setup
    d = client.dict("u")
    await d.set("a", {"v": 1})
    popped = await d.pop("a")
    assert popped == {"v": 1}
    with pytest.raises(KeyError):
        await d.get("a")


@pytest.mark.asyncio
async def test_clear(setup):
    db, client = setup
    d = client.dict("u")
    await d.set("a", {"v": 1})
    await d.set("b", {"v": 2})
    await d.clear()
    assert await d.count() == 0

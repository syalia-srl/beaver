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
async def test_log_then_count(setup):
    db, client = setup
    lg = client.log("events")
    await lg.log({"event": "a"})
    await lg.log({"event": "b"})
    assert await lg.count() == 2


@pytest.mark.asyncio
async def test_log_with_explicit_timestamp(setup):
    db, client = setup
    lg = client.log("events")
    await lg.log({"event": "a"}, timestamp=100.0)
    await lg.log({"event": "b"}, timestamp=200.0)
    entries = await lg.range()
    assert len(entries) == 2
    assert entries[0]["timestamp"] == 100.0
    assert entries[0]["data"] == {"event": "a"}
    assert entries[1]["timestamp"] == 200.0


@pytest.mark.asyncio
async def test_range_with_bounds(setup):
    db, client = setup
    lg = client.log("events")
    for i, ts in enumerate([100.0, 200.0, 300.0]):
        await lg.log({"i": i}, timestamp=ts)
    entries = await lg.range(start=150.0, end=250.0)
    assert len(entries) == 1
    assert entries[0]["data"] == {"i": 1}


@pytest.mark.asyncio
async def test_range_limit(setup):
    db, client = setup
    lg = client.log("events")
    for i in range(5):
        await lg.log({"i": i}, timestamp=float(100 + i))
    entries = await lg.range(limit=2)
    assert len(entries) == 2


@pytest.mark.asyncio
async def test_clear(setup):
    db, client = setup
    lg = client.log("events")
    await lg.log({"event": "a"})
    await lg.clear()
    assert await lg.count() == 0

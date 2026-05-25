import httpx
import pytest
from httpx import ASGITransport

from beaver.server import create_app
from beaver.core import AsyncBeaverDB


@pytest.fixture
async def client(tmp_path):
    db = AsyncBeaverDB(str(tmp_path / "test.db"))
    await db.connect()
    app = create_app(db)
    async with httpx.AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test") as c:
        yield c
    await db.close()


@pytest.mark.asyncio
async def test_get_missing_key_returns_404_envelope(client):
    r = await client.get("/dicts/u/alice")
    assert r.status_code == 404
    body = r.json()
    assert body["error"] == "KeyError"
    assert "alice" in body["message"]
    assert body["detail"] is None

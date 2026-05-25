import httpx
import pytest
from httpx import ASGITransport

from beaver.server import create_app
from beaver.core import AsyncBeaverDB


async def _make_client(tmp_path, api_key):
    db = AsyncBeaverDB(str(tmp_path / "test.db"))
    await db.connect()
    app = create_app(db, api_key=api_key)
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    return db, httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_no_key_required_when_server_started_without_key(tmp_path):
    db, client = await _make_client(tmp_path, api_key=None)
    try:
        r = await client.get("/dicts/u/alice")
        assert r.status_code == 404  # KeyError, not 401
    finally:
        await client.aclose()
        await db.close()


@pytest.mark.asyncio
async def test_missing_bearer_when_required_returns_401(tmp_path):
    db, client = await _make_client(tmp_path, api_key="secret")
    try:
        r = await client.get("/dicts/u/alice")
        assert r.status_code == 401
        assert r.json()["error"] == "AuthError"
    finally:
        await client.aclose()
        await db.close()


@pytest.mark.asyncio
async def test_valid_bearer_passes(tmp_path):
    db, client = await _make_client(tmp_path, api_key="secret")
    try:
        r = await client.get("/dicts/u/alice", headers={"Authorization": "Bearer secret"})
        assert r.status_code == 404  # KeyError, auth passed
    finally:
        await client.aclose()
        await db.close()


@pytest.mark.asyncio
async def test_wrong_bearer_returns_401(tmp_path):
    db, client = await _make_client(tmp_path, api_key="secret")
    try:
        r = await client.get("/dicts/u/alice", headers={"Authorization": "Bearer wrong"})
        assert r.status_code == 401
    finally:
        await client.aclose()
        await db.close()

import httpx
import pytest
from httpx import ASGITransport

from beaver.server import create_app
from beaver.core import AsyncBeaverDB
from beaver.client import AsyncBeaverClient
from beaver.errors import LocalOnlyError


async def _make_client(tmp_path):
    db = AsyncBeaverDB(str(tmp_path / "test.db"))
    await db.connect()
    app = create_app(db)
    client = AsyncBeaverClient.__new__(AsyncBeaverClient)
    client._http = httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    )
    return db, client


@pytest.mark.asyncio
async def test_remote_keys_raises_local_only(tmp_path):
    db, client = await _make_client(tmp_path)
    try:
        d = client.dict("u")
        with pytest.raises(LocalOnlyError, match="local"):
            async for _ in d.keys():
                pass
    finally:
        await client.close()
        await db.close()


@pytest.mark.asyncio
async def test_remote_batched_raises_local_only(tmp_path):
    db, client = await _make_client(tmp_path)
    try:
        d = client.dict("u")
        with pytest.raises(LocalOnlyError, match="transactional"):
            d.batched()
    finally:
        await client.close()
        await db.close()


@pytest.mark.asyncio
async def test_remote_list_batched_raises_local_only(tmp_path):
    db, client = await _make_client(tmp_path)
    try:
        lst = client.list("u")
        with pytest.raises(LocalOnlyError, match="transactional"):
            lst.batched()
    finally:
        await client.close()
        await db.close()


@pytest.mark.asyncio
async def test_remote_list_dump_raises_local_only(tmp_path):
    db, client = await _make_client(tmp_path)
    try:
        lst = client.list("u")
        with pytest.raises(LocalOnlyError, match="local"):
            await lst.dump()
    finally:
        await client.close()
        await db.close()


@pytest.mark.asyncio
async def test_remote_queue_dump_raises_local_only(tmp_path):
    db, client = await _make_client(tmp_path)
    try:
        q = client.queue("u")
        with pytest.raises(LocalOnlyError, match="local"):
            await q.dump()
    finally:
        await client.close()
        await db.close()

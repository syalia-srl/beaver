import pytest

import beaver
from beaver.core import AsyncBeaverDB, BeaverDB
from beaver.client import AsyncBeaverClient, BeaverClient


def test_connect_local_sync_returns_beaver_db(tmp_path):
    db = beaver.connect(str(tmp_path / "x.db"))
    try:
        assert isinstance(db, BeaverDB)
    finally:
        db.close()


@pytest.mark.asyncio
async def test_connect_local_async_returns_async_beaver_db(tmp_path):
    db = beaver.connect(str(tmp_path / "x.db"), sync=False)
    try:
        assert isinstance(db, AsyncBeaverDB)
    finally:
        await db.close()


def test_connect_http_sync_returns_beaver_client():
    client = beaver.connect("http://localhost:9999", api_key="k")
    try:
        assert isinstance(client, BeaverClient)
    finally:
        client.close()


@pytest.mark.asyncio
async def test_connect_http_async_returns_async_beaver_client():
    client = beaver.connect("http://localhost:9999", sync=False, api_key="k")
    try:
        assert isinstance(client, AsyncBeaverClient)
    finally:
        await client.close()


def test_connect_https_also_routes_to_client():
    client = beaver.connect("https://example.test:443", api_key="k")
    try:
        assert isinstance(client, BeaverClient)
    finally:
        client.close()

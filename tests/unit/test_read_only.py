"""Read-only connections inspect an existing Beaver file without changing it."""

import hashlib
import sqlite3

import pytest

import beaver
from beaver import (
    AsyncBeaverDB,
    BeaverIncompleteSchemaError,
    BeaverIncompatibleSchemaError,
    BeaverLegacySchemaError,
)
from beaver.core import BEAVER_DB_VERSION
from beaver.errors import LocalOnlyError


pytestmark = pytest.mark.asyncio


def _digest(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def test_read_only_opens_existing_beaver_database_without_writing(tmp_path):
    path = tmp_path / "existing database #1?.db"
    writable = await AsyncBeaverDB(str(path)).connect()
    await writable.dict("demo").set("answer", 42)
    await writable.close()
    before = _digest(path)

    db = await AsyncBeaverDB(str(path), read_only=True).connect()
    try:
        assert db.read_only is True
        assert db.path == str(path)
        cursor = await db.connection.execute(
            "SELECT value FROM __beaver_dicts__ WHERE dict_name = ? AND key = ?",
            ("demo", "answer"),
        )
        assert (await cursor.fetchone())[0] == "42"
        cursor = await db.connection.execute("PRAGMA query_only")
        assert (await cursor.fetchone())[0] == 1
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            await db.connection.execute(
                "INSERT INTO __beaver_dicts__ VALUES (?, ?, ?, ?)",
                ("demo", "other", "43", None),
            )
    finally:
        await db.close()

    assert _digest(path) == before


async def test_read_only_missing_path_does_not_create_file(tmp_path):
    path = tmp_path / "missing.db"

    with pytest.raises(FileNotFoundError, match="read-only"):
        await AsyncBeaverDB(str(path), read_only=True).connect()

    assert not path.exists()


async def test_read_only_rejects_memory_database():
    with pytest.raises(ValueError, match="memory"):
        AsyncBeaverDB(":memory:", read_only=True)


async def test_read_only_rejects_partial_schema_without_repairing_it(tmp_path):
    path = tmp_path / "partial.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE __beaver_dicts__ ("
        "dict_name TEXT, key TEXT, value TEXT, expires_at REAL)"
    )
    conn.execute(f"PRAGMA user_version = {BEAVER_DB_VERSION}")
    conn.commit()
    conn.close()
    before = _digest(path)

    with pytest.raises(BeaverIncompleteSchemaError, match="incomplete") as exc_info:
        await AsyncBeaverDB(str(path), read_only=True).connect()

    assert "__beaver_lists__" in str(exc_info.value)
    assert _digest(path) == before


async def test_read_only_rejects_empty_sqlite_database(tmp_path):
    path = tmp_path / "empty.db"
    sqlite3.connect(path).close()

    with pytest.raises(BeaverIncompleteSchemaError):
        await AsyncBeaverDB(str(path), read_only=True).connect()


async def test_read_only_rejects_rc3_even_when_lists_table_is_empty(tmp_path):
    path = tmp_path / "rc3.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE __beaver_lists__ ("
        "list_name TEXT NOT NULL, item_order REAL NOT NULL, "
        "item_value TEXT NOT NULL, PRIMARY KEY (list_name, item_order))"
    )
    conn.commit()
    conn.close()
    before = _digest(path)

    with pytest.raises(BeaverIncompatibleSchemaError, match="rc4"):
        await AsyncBeaverDB(str(path), read_only=True).connect()

    assert _digest(path) == before


async def test_read_only_rejects_database_from_newer_beaver_without_changes(tmp_path):
    path = tmp_path / "newer.db"
    conn = sqlite3.connect(path)
    conn.execute(f"PRAGMA user_version = {BEAVER_DB_VERSION + 1}")
    conn.commit()
    conn.close()
    before = _digest(path)

    with pytest.raises(BeaverIncompatibleSchemaError, match="newer"):
        await AsyncBeaverDB(str(path), read_only=True).connect()

    assert _digest(path) == before


@pytest.mark.parametrize("split_brain", [False, True])
async def test_read_only_rejects_legacy_and_split_brain_without_changes(
    tmp_path, split_brain
):
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE beaver_dicts ("
        "dict_name TEXT, key TEXT, value TEXT, expires_at REAL)"
    )
    if split_brain:
        conn.execute(
            "CREATE TABLE __beaver_dicts__ ("
            "dict_name TEXT, key TEXT, value TEXT, expires_at REAL)"
        )
        conn.execute(f"PRAGMA user_version = {BEAVER_DB_VERSION}")
    conn.commit()
    conn.close()
    before = _digest(path)

    with pytest.raises(BeaverLegacySchemaError) as exc_info:
        await AsyncBeaverDB(str(path), read_only=True).connect()

    assert ("split-brain" in str(exc_info.value).lower()) is split_brain
    assert _digest(path) == before


async def test_public_connect_passes_read_only_to_local_databases(tmp_path):
    path = tmp_path / "public.db"
    writable = await AsyncBeaverDB(str(path)).connect()
    await writable.close()

    async_db = beaver.connect(str(path), sync=False, read_only=True)
    assert async_db.read_only is True
    await async_db.connect()
    await async_db.close()


async def test_public_connect_rejects_read_only_for_remote_sources():
    with pytest.raises(LocalOnlyError, match="local"):
        beaver.connect("https://example.test", read_only=True)


async def test_incomplete_error_is_public_and_registered():
    from beaver.errors import ErrorEnvelope, raise_from_envelope

    with pytest.raises(BeaverIncompleteSchemaError):
        raise_from_envelope(
            ErrorEnvelope(error="BeaverIncompleteSchemaError", message="incomplete")
        )

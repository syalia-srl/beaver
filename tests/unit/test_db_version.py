"""Tests for the DB version gate added in rc4.

rc4 uses SQLite's PRAGMA user_version to detect databases written by older
beaver versions (which used REAL item_order in __beaver_lists__). Opening
such a database against rc4 must raise BeaverIncompatibleSchemaError unless
the list table is empty (in which case we silently upgrade).

2.x additionally refuses genuine beaver 1.x databases, which use single-prefix
table names (beaver_dicts, ...) instead of the dunder names 2.x writes. See
issues/41.
"""

import asyncio
import sqlite3
import uuid

import pytest

from beaver import AsyncBeaverDB, BeaverDB, BeaverIncompatibleSchemaError
from beaver.core import BEAVER_DB_VERSION, BeaverLegacySchemaError

pytestmark = pytest.mark.asyncio


def _make_1x_db(path: str, *, version: str | None = "1.3.0") -> None:
    """Write a database shaped like one created by beaver 1.x.

    Built with plain sqlite3 so the test suite never needs beaver 1.x
    installed. Mirrors the real 1.x schema: single-prefix table names, REAL
    item_order, and the version stamp inside beaver_dicts.
    """
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE beaver_dicts (
            dict_name TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            expires_at REAL,
            PRIMARY KEY (dict_name, key)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE beaver_lists (
            list_name TEXT NOT NULL,
            item_order REAL NOT NULL,
            item_value TEXT NOT NULL,
            PRIMARY KEY (list_name, item_order)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE beaver_collections (
            collection_name TEXT NOT NULL,
            doc_id TEXT NOT NULL,
            content TEXT NOT NULL,
            PRIMARY KEY (collection_name, doc_id)
        )
        """
    )
    if version is not None:
        conn.execute(
            "INSERT INTO beaver_dicts (dict_name, key, value) VALUES (?, ?, ?)",
            ("__metadata__", "version", f'"{version}"'),
        )
    conn.execute(
        "INSERT INTO beaver_dicts (dict_name, key, value) VALUES (?, ?, ?)",
        ("conv:c1:meta", "title", '"My important conversation"'),
    )
    conn.execute(
        "INSERT INTO beaver_lists (list_name, item_order, item_value) VALUES (?, ?, ?)",
        ("conv:c1:pairs", 1.0, '{"user": "hello"}'),
    )
    conn.commit()
    conn.close()


def _make_rc3_db_with_list(path: str, with_row: bool) -> None:
    """Write a database that looks like one created by rc3 (no user_version
    set, REAL item_order column)."""
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE __beaver_lists__ (
            list_name TEXT NOT NULL,
            item_order REAL NOT NULL,
            item_value TEXT NOT NULL,
            PRIMARY KEY (list_name, item_order)
        )
        """
    )
    if with_row:
        conn.execute(
            "INSERT INTO __beaver_lists__ (list_name, item_order, item_value) VALUES (?, ?, ?)",
            ("seed", 1.0, '"hello"'),
        )
    conn.commit()
    conn.close()


@pytest.fixture
def tmp_db(tmp_path):
    return str(tmp_path / f"{uuid.uuid4().hex}.db")


async def test_fresh_db_sets_user_version(tmp_db):
    db = AsyncBeaverDB(tmp_db)
    await db.connect()
    try:
        cursor = await db._connection.execute("PRAGMA user_version")
        row = await cursor.fetchone()
        assert row[0] == BEAVER_DB_VERSION
    finally:
        await db.close()


async def test_rc3_db_with_lists_data_raises(tmp_db):
    _make_rc3_db_with_list(tmp_db, with_row=True)
    db = AsyncBeaverDB(tmp_db)
    with pytest.raises(BeaverIncompatibleSchemaError):
        await db.connect()


async def test_rc3_db_with_empty_lists_upgrades(tmp_db):
    _make_rc3_db_with_list(tmp_db, with_row=False)
    db = AsyncBeaverDB(tmp_db)
    await db.connect()
    try:
        cursor = await db._connection.execute("PRAGMA user_version")
        row = await cursor.fetchone()
        assert row[0] == BEAVER_DB_VERSION
        cursor = await db._connection.execute(
            "SELECT type FROM pragma_table_info('__beaver_lists__') WHERE name = 'item_order'"
        )
        row = await cursor.fetchone()
        assert row[0] == "TEXT"
    finally:
        await db.close()


async def test_newer_db_raises(tmp_db):
    conn = sqlite3.connect(tmp_db)
    conn.execute(f"PRAGMA user_version = {BEAVER_DB_VERSION + 99}")
    conn.commit()
    conn.close()
    db = AsyncBeaverDB(tmp_db)
    with pytest.raises(BeaverIncompatibleSchemaError):
        await db.connect()


# --- beaver 1.x legacy schema detection (issues/41) ---------------------------


async def test_legacy_1x_db_raises(tmp_db):
    """A genuine 1.x database must be refused, not opened as if empty."""
    _make_1x_db(tmp_db)
    db = AsyncBeaverDB(tmp_db)
    with pytest.raises(BeaverLegacySchemaError) as exc_info:
        await db.connect()

    message = str(exc_info.value)
    assert "1.3.0" in message, "error must name the detected legacy version"
    assert "beaver_dicts" in message, "error must name the detected legacy tables"
    assert "migration-1x-to-2x" in message, "error must point at the migration path"


async def test_legacy_1x_db_is_an_incompatible_schema_error(tmp_db):
    """Existing consumers catching the broader class keep working."""
    _make_1x_db(tmp_db)
    db = AsyncBeaverDB(tmp_db)
    with pytest.raises(BeaverIncompatibleSchemaError):
        await db.connect()


async def test_legacy_1x_db_leaves_the_file_untouched(tmp_db):
    """Refusing must not create the 2.x tables or stamp user_version."""
    _make_1x_db(tmp_db)
    db = AsyncBeaverDB(tmp_db)
    with pytest.raises(BeaverLegacySchemaError):
        await db.connect()

    conn = sqlite3.connect(tmp_db)
    try:
        names = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert not any(n.startswith("__beaver_") for n in names)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
    finally:
        conn.close()


async def test_legacy_1x_db_without_version_stamp_raises(tmp_db):
    """A legacy file with no __metadata__ version still gets refused."""
    _make_1x_db(tmp_db, version=None)
    db = AsyncBeaverDB(tmp_db)
    with pytest.raises(BeaverLegacySchemaError) as exc_info:
        await db.connect()

    assert "unknown" in str(exc_info.value).lower()


async def test_split_brain_db_raises_distinctly(tmp_db):
    """Legacy + dunder tables means 2.x already wrote beside the 1.x data.

    Such a database has also been stamped to the current user_version by that
    accidental open, so detection must run before the user_version fast path.
    """
    _make_1x_db(tmp_db)
    conn = sqlite3.connect(tmp_db)
    conn.execute(
        """
        CREATE TABLE __beaver_dicts__ (
            dict_name TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            expires_at REAL,
            PRIMARY KEY (dict_name, key)
        )
        """
    )
    conn.execute(f"PRAGMA user_version = {BEAVER_DB_VERSION}")
    conn.commit()
    conn.close()

    db = AsyncBeaverDB(tmp_db)
    with pytest.raises(BeaverLegacySchemaError) as exc_info:
        await db.connect()

    message = str(exc_info.value)
    assert "split-brain" in message.lower()
    assert "__beaver_dicts__" in message


async def test_legacy_1x_db_raises_through_sync_facade(tmp_db):
    """The sync portal must surface the same refusal, not swallow it."""
    _make_1x_db(tmp_db)
    with pytest.raises(BeaverLegacySchemaError):
        await asyncio.to_thread(BeaverDB, tmp_db)


# --- regression guards for the detection change ------------------------------


async def test_existing_2x_db_reopens_cleanly(tmp_db):
    db = AsyncBeaverDB(tmp_db)
    await db.connect()
    await db.dict("greetings").set("hello", "world")
    await db.close()

    db = AsyncBeaverDB(tmp_db)
    await db.connect()
    try:
        assert await db.dict("greetings").get("hello") == "world"
    finally:
        await db.close()


async def test_memory_db_connects():
    db = AsyncBeaverDB(":memory:")
    await db.connect()
    try:
        cursor = await db._connection.execute("PRAGMA user_version")
        row = await cursor.fetchone()
        assert row[0] == BEAVER_DB_VERSION
    finally:
        await db.close()

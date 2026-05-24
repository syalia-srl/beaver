"""Tests for the DB version gate added in rc4.

rc4 uses SQLite's PRAGMA user_version to detect databases written by older
beaver versions (which used REAL item_order in __beaver_lists__). Opening
such a database against rc4 must raise BeaverIncompatibleSchemaError unless
the list table is empty (in which case we silently upgrade).
"""

import sqlite3
import uuid

import pytest

from beaver import AsyncBeaverDB, BeaverIncompatibleSchemaError
from beaver.core import BEAVER_DB_VERSION

pytestmark = pytest.mark.asyncio


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

"""Tests for the beaver 1.x -> 2.x migrator (issues/41, slice 2).

Legacy fixtures are built directly with sqlite3 so the suite never needs
beaver 1.3.0 installed.
"""

import hashlib
import json
import os
import sqlite3
import uuid

import numpy as np
import pytest

from beaver import AsyncBeaverDB, BeaverLegacySchemaError
from beaver.migrate import format_report, migrate_database, plan_migration

pytestmark = pytest.mark.asyncio


LEGACY_DDL = [
    """CREATE TABLE beaver_dicts (dict_name TEXT NOT NULL, key TEXT NOT NULL,
       value TEXT NOT NULL, expires_at REAL, PRIMARY KEY (dict_name, key))""",
    """CREATE TABLE beaver_lists (list_name TEXT NOT NULL, item_order REAL NOT NULL,
       item_value TEXT NOT NULL, PRIMARY KEY (list_name, item_order))""",
    """CREATE TABLE beaver_collections (collection TEXT NOT NULL, item_id TEXT NOT NULL,
       item_vector BLOB, metadata TEXT, PRIMARY KEY (collection, item_id))""",
    """CREATE TABLE beaver_logs (log_name TEXT NOT NULL, timestamp REAL NOT NULL,
       data TEXT NOT NULL, PRIMARY KEY (log_name, timestamp))""",
    """CREATE TABLE beaver_blobs (store_name TEXT NOT NULL, key TEXT NOT NULL,
       data BLOB NOT NULL, metadata TEXT, PRIMARY KEY (store_name, key))""",
    """CREATE TABLE beaver_manager_versions (namespace TEXT PRIMARY KEY,
       version INTEGER NOT NULL DEFAULT 0)""",
    """CREATE TABLE beaver_vector_change_log (log_id INTEGER PRIMARY KEY AUTOINCREMENT,
       collection_name TEXT NOT NULL, item_id TEXT NOT NULL, operation_type INTEGER NOT NULL)""",
    """CREATE TABLE beaver_trigrams (collection TEXT NOT NULL, item_id TEXT NOT NULL,
       field_path TEXT NOT NULL, trigram TEXT NOT NULL,
       PRIMARY KEY (collection, field_path, trigram, item_id))""",
]


def make_legacy_db(path: str, *, version: str = "1.3.0") -> sqlite3.Connection:
    """Create an empty 1.x-shaped database and return an open connection."""
    conn = sqlite3.connect(path)
    for ddl in LEGACY_DDL:
        conn.execute(ddl)
    conn.execute(
        "INSERT INTO beaver_dicts (dict_name, key, value) VALUES (?, ?, ?)",
        ("__metadata__", "version", f'"{version}"'),
    )
    return conn


def put_dict(conn, name, key, value) -> None:
    conn.execute(
        "INSERT INTO beaver_dicts (dict_name, key, value) VALUES (?, ?, ?)",
        (name, key, json.dumps(value)),
    )


def put_list(conn, name, values) -> None:
    for i, v in enumerate(values, start=1):
        conn.execute(
            "INSERT INTO beaver_lists (list_name, item_order, item_value) VALUES (?, ?, ?)",
            (name, float(i), json.dumps(v)),
        )


@pytest.fixture
def paths(tmp_path):
    stem = uuid.uuid4().hex
    return str(tmp_path / f"{stem}.db"), str(tmp_path / f"{stem}.migrated.db")


async def test_migrates_dicts_and_lists(paths):
    src, dst = paths
    conn = make_legacy_db(src)
    put_dict(conn, "settings", "theme", "dark")
    put_dict(conn, "settings", "lang", "es")
    put_list(conn, "events", ["first", "second", "third"])
    conn.commit()
    conn.close()

    report = await migrate_database(src, dst)
    assert report.dicts == {"settings": 2}
    assert report.lists == {"events": 3}

    db = await AsyncBeaverDB(dst).connect()
    try:
        assert await db.dict("settings").get("theme") == "dark"
        assert await db.dict("settings").count() == 2
        assert [x async for x in db.list("events")] == ["first", "second", "third"]
    finally:
        await db.close()


async def test_metadata_version_row_is_not_migrated(paths):
    src, dst = paths
    conn = make_legacy_db(src)
    conn.commit()
    conn.close()

    await migrate_database(src, dst)

    db = await AsyncBeaverDB(dst).connect()
    try:
        cursor = await db.connection.execute(
            "SELECT COUNT(*) FROM __beaver_dicts__ WHERE dict_name = '__metadata__'"
        )
        assert (await cursor.fetchone())[0] == 0
    finally:
        await db.close()


async def test_preserves_list_order_past_the_rc3_float_limit(paths):
    """1.x's REAL midpoint scheme collapsed after ~52 same-index inserts.

    The regenerated fractional index must hold exact order well beyond that.
    """
    src, dst = paths
    conn = make_legacy_db(src)
    expected = [f"item-{i:03d}" for i in range(200)]
    put_list(conn, "big", expected)
    conn.commit()
    conn.close()

    await migrate_database(src, dst)

    db = await AsyncBeaverDB(dst).connect()
    try:
        assert [x async for x in db.list("big")] == expected
    finally:
        await db.close()


async def test_encrypted_dict_values_round_trip(paths):
    """Secret-encrypted values must survive as opaque ciphertext.

    The migrator never decrypts and needs no key material: it copies the value
    column verbatim, and the salt/verifier live in the `__security__` dict,
    which is carried across like any other dict.
    """
    pytest.importorskip("cryptography")
    src, dst = paths
    secret = "master-secret-value"

    # Produce genuine ciphertext with 2.x, then transplant those exact rows
    # into a 1.x-shaped file.
    staging = src + ".staging"
    db = await AsyncBeaverDB(staging).connect()
    try:
        await db.dict("users", secret=secret).set("alice", {"role": "admin"})
        cursor = await db.connection.execute(
            "SELECT dict_name, key, value, expires_at FROM __beaver_dicts__"
        )
        rows = await cursor.fetchall()
    finally:
        await db.close()

    conn = make_legacy_db(src)
    for row in rows:
        conn.execute(
            "INSERT INTO beaver_dicts (dict_name, key, value, expires_at) VALUES (?, ?, ?, ?)",
            tuple(row),
        )
    conn.commit()
    conn.close()

    # The value on disk must be ciphertext, not readable JSON.
    check = sqlite3.connect(src)
    stored = check.execute(
        "SELECT value FROM beaver_dicts WHERE dict_name='users' AND key='alice'"
    ).fetchone()[0]
    check.close()
    assert "admin" not in stored

    await migrate_database(src, dst)

    db = await AsyncBeaverDB(dst).connect()
    try:
        assert await db.dict("users", secret=secret).get("alice") == {"role": "admin"}
    finally:
        await db.close()

    # Fresh connection: the salt/verifier carried across, so the wrong secret
    # is still rejected. (A second db.dict() on the same connection would hand
    # back the cached, already-unlocked manager.)
    db = await AsyncBeaverDB(dst).connect()
    try:
        with pytest.raises(ValueError):
            await db.dict("users", secret="wrong-secret").get("alice")
    finally:
        await db.close()


async def test_collections_fan_out_to_documents_and_vectors(paths):
    """1.x fused documents and embeddings into one table; 2.x splits them."""
    src, dst = paths
    conn = make_legacy_db(src)
    vector = np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float32)
    body = {"doc_name": "letter.pdf", "content": "Habana lorem ipsum", "chunk_index": 0}
    conn.execute(
        "INSERT INTO beaver_collections (collection, item_id, item_vector, metadata) VALUES (?, ?, ?, ?)",
        ("chunks", "item-1", vector.tobytes(), json.dumps(body)),
    )
    # A row with a document but no embedding must still land in documents.
    conn.execute(
        "INSERT INTO beaver_collections (collection, item_id, item_vector, metadata) VALUES (?, ?, ?, ?)",
        ("chunks", "item-2", None, json.dumps({"content": "no vector here"})),
    )
    conn.commit()
    conn.close()

    report = await migrate_database(src, dst)
    assert report.documents == {"chunks": 2}
    assert report.vectors == {"chunks": 1}

    db = await AsyncBeaverDB(dst).connect()
    try:
        doc = await db.docs("chunks").get("item-1")
        assert doc.body["doc_name"] == "letter.pdf"
        assert await db.docs("chunks").count() == 2
        assert await db.vectors("chunks").count() == 1

        item = await db.vectors("chunks").get("item-1")
        assert np.allclose(np.array(item.vector, dtype=np.float32), vector)

        # FTS was rebuilt from the migrated documents, not copied.
        hits = await db.docs("chunks").search("Habana")
        assert [h.document.id for h in hits] == ["item-1"]
    finally:
        await db.close()


async def test_reads_an_uncheckpointed_wal(paths):
    """Rows sitting only in a hot WAL must be migrated, not silently skipped."""
    src, dst = paths
    conn = make_legacy_db(src)
    conn.commit()
    conn.close()

    hot = sqlite3.connect(src)
    hot.execute("PRAGMA journal_mode = WAL")
    hot.execute("PRAGMA wal_autocheckpoint = 0")
    put_dict(hot, "late", "written", "in-wal")
    put_list(hot, "late-list", ["a", "b"])
    hot.commit()
    assert os.path.exists(src + "-wal"), "test needs an un-checkpointed WAL"
    assert os.path.getsize(src + "-wal") > 0
    hot.close()

    report = await migrate_database(src, dst)
    assert report.dicts.get("late") == 1

    db = await AsyncBeaverDB(dst).connect()
    try:
        assert await db.dict("late").get("written") == "in-wal"
        assert [x async for x in db.list("late-list")] == ["a", "b"]
    finally:
        await db.close()


async def test_source_is_left_byte_identical(paths):
    src, dst = paths
    conn = make_legacy_db(src)
    put_dict(conn, "settings", "theme", "dark")
    conn.commit()
    conn.close()

    def digest(path):
        return hashlib.sha256(open(path, "rb").read()).hexdigest()

    before = digest(src)
    await migrate_database(src, dst)
    assert digest(src) == before


async def test_migrated_database_opens_with_2x(paths):
    src, dst = paths
    conn = make_legacy_db(src)
    put_dict(conn, "settings", "theme", "dark")
    conn.commit()
    conn.close()

    await migrate_database(src, dst)

    # No BeaverLegacySchemaError, and no legacy tables carried across.
    db = await AsyncBeaverDB(dst).connect()
    try:
        cursor = await db.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        names = {row[0] for row in await cursor.fetchall()}
    finally:
        await db.close()
    assert not any(n in names for n in ("beaver_dicts", "beaver_lists"))


def make_split_brain(src: str) -> None:
    """A 1.x file that some 2.x process already wrote into."""
    conn = make_legacy_db(src)
    put_dict(conn, "settings", "theme", "dark")
    put_list(conn, "events", ["a", "b", "c"])
    conn.execute(
        """CREATE TABLE __beaver_dicts__ (dict_name TEXT NOT NULL, key TEXT NOT NULL,
           value TEXT NOT NULL, expires_at REAL, PRIMARY KEY (dict_name, key))"""
    )
    conn.execute(
        """CREATE TABLE __beaver_lists__ (list_name TEXT NOT NULL, item_order TEXT NOT NULL,
           item_value TEXT NOT NULL, PRIMARY KEY (list_name, item_order))"""
    )
    conn.execute(
        "INSERT INTO __beaver_dicts__ (dict_name, key, value) VALUES (?, ?, ?)",
        ("settings", "theme", '"light"'),
    )
    conn.execute(
        "INSERT INTO __beaver_dicts__ (dict_name, key, value) VALUES (?, ?, ?)",
        ("sessions", "sid-1", '"active"'),
    )
    conn.execute(
        "INSERT INTO __beaver_lists__ (list_name, item_order, item_value) VALUES (?, ?, ?)",
        ("events", "a0", '"d"'),
    )
    conn.commit()
    conn.close()


async def test_refuses_split_brain_source(paths):
    src, dst = paths
    make_split_brain(src)

    with pytest.raises(BeaverLegacySchemaError, match="SPLIT-BRAIN"):
        await migrate_database(src, dst)
    assert not os.path.exists(dst)


async def test_dry_run_describes_split_brain_instead_of_refusing(paths):
    """The real run refuses, but the dry run must still report both sides.

    An operator who hits the split-brain error needs row counts on each side to
    decide which dataset matters; refusing here would leave them without a tool
    to investigate the situation the error told them to investigate.
    """
    src, _ = paths
    make_split_brain(src)

    report = plan_migration(src)

    assert report.split_brain is True
    # 1.x side, reported as usual.
    assert report.dicts == {"settings": 1}
    assert report.lists == {"events": 3}
    # 2.x side, reported separately and per store.
    assert report.modern["dicts"] == {"settings": 1, "sessions": 1}
    assert report.modern["lists"] == {"events": 1}

    rendered = format_report(report)
    assert "SPLIT-BRAIN" in rendered
    assert "CANNOT BE MIGRATED" in rendered
    assert "1.x side" in rendered and "2.x side" in rendered
    assert "sessions" in rendered
    assert "No migration path exists without a human decision" in rendered


async def test_refuses_a_non_legacy_source(paths):
    src, dst = paths
    db = await AsyncBeaverDB(src).connect()
    await db.close()

    with pytest.raises(BeaverLegacySchemaError, match="nothing to migrate"):
        await migrate_database(src, dst)


async def test_refuses_an_existing_destination(paths):
    src, dst = paths
    conn = make_legacy_db(src)
    conn.commit()
    conn.close()
    open(dst, "w").close()

    with pytest.raises(FileExistsError):
        await migrate_database(src, dst)


async def test_dry_run_writes_nothing_and_reports(paths):
    src, dst = paths
    conn = make_legacy_db(src)
    put_dict(conn, "settings", "theme", "dark")
    put_list(conn, "events", ["a", "b", "c"])
    conn.execute(
        "INSERT INTO beaver_vector_change_log (collection_name, item_id, operation_type) VALUES (?,?,?)",
        ("chunks", "x", 1),
    )
    conn.commit()
    conn.close()

    before = set(os.listdir(os.path.dirname(src)))
    report = plan_migration(src)

    assert report.dry_run is True
    assert report.destination is None
    assert report.legacy_version == "1.3.0"
    assert report.dicts == {"settings": 1}
    assert report.lists == {"events": 3}
    assert "beaver_vector_change_log" in report.dropped
    assert "beaver_fts_index" not in report.rebuilt  # not present in this fixture
    assert report.total_rows == 4
    assert set(os.listdir(os.path.dirname(src))) == before

    rendered = format_report(report)
    assert "settings" in rendered and "dry run" in rendered

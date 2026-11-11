"""Opening a sealed database read-only (issue #55).

A database baked into a read-only image, or a file mode 0444 in a directory
mode 0555, must open for reading without beaver writing anything: no WAL
sidecars, no schema creation, no user_version stamp. Writes must fail with
beaver's own error instead of sqlite3's ``attempt to write a readonly
database``.
"""

import contextlib
import os
import time
from pathlib import Path

import pytest

from beaver import AsyncBeaverDB, BeaverDB, BeaverReadOnlyError


def _build(path: str) -> None:
    """Write the fixture dataset through the public API, then close."""
    with BeaverDB(path) as db:
        settings = db.dict("settings")
        settings["shop"] = "Spoke & Chain"
        settings["hours"] = {"open": 9, "close": 18}
        settings["greeting"] = "hello"

        db.docs("tickets").index(
            id="T-1",
            body={"title": "Broken bell", "body": "The bell above the door is broken"},
        )

        thread = db.list("thread")
        thread.push("first")
        thread.push("second")


def _expected(path: str) -> dict:
    """What a normal read-write open sees."""
    with BeaverDB(path) as db:
        docs = db.docs("tickets")
        return {
            "items": dict(db.dict("settings").items()),
            "length": len(db.dict("settings")),
            "document": docs.get("T-1").body,
            "search": [hit.document.id for hit in docs.search("bell")],
            "list": list(db.list("thread")),
        }


@contextlib.contextmanager
def _sealed(tmp_path: Path, path: str):
    """Make the file 0444 in a 0555 directory, restoring in all cases."""
    os.chmod(path, 0o444)
    os.chmod(tmp_path, 0o555)
    try:
        yield
    finally:
        os.chmod(tmp_path, 0o755)
        os.chmod(path, 0o644)


def test_sync_read_only_sees_the_same_data_and_adds_no_files(tmp_path):
    path = str(tmp_path / "sealed.db")
    _build(path)
    expected = _expected(path)

    with _sealed(tmp_path, path):
        with BeaverDB(path, read_only=True) as db:
            settings = db.dict("settings")
            docs = db.docs("tickets")
            assert dict(settings.items()) == expected["items"]
            assert len(settings) == expected["length"]
            assert docs.get("T-1").body == expected["document"]
            assert [hit.document.id for hit in docs.search("bell")] == expected[
                "search"
            ]
            assert list(db.list("thread")) == expected["list"]

        assert sorted(os.listdir(tmp_path)) == ["sealed.db"]


async def test_async_read_only_sees_the_same_data_and_adds_no_files(tmp_path):
    path = str(tmp_path / "sealed.db")
    _build(path)
    expected = _expected(path)

    with _sealed(tmp_path, path):
        db = AsyncBeaverDB(path, read_only=True)
        await db.connect()
        try:
            settings = db.dict("settings")
            docs = db.docs("tickets")
            assert {k: v async for k, v in settings.items()} == expected["items"]
            assert await settings.count() == expected["length"]
            assert (await docs.get("T-1")).body == expected["document"]
            found = await docs.search("bell")
            assert [hit.document.id for hit in found] == expected["search"]
            assert [item async for item in db.list("thread")] == expected["list"]
        finally:
            await db.close()

        assert sorted(os.listdir(tmp_path)) == ["sealed.db"]


async def test_async_write_on_read_only_open_raises_beaver_error(tmp_path):
    path = str(tmp_path / "sealed.db")
    _build(path)

    with _sealed(tmp_path, path):
        db = AsyncBeaverDB(path, read_only=True)
        await db.connect()
        try:
            with pytest.raises(BeaverReadOnlyError) as exc_info:
                await db.dict("settings").set("shop", "somewhere else")
            assert "read-only" in str(exc_info.value).lower()

            with pytest.raises(BeaverReadOnlyError):
                await db.docs("tickets").index(id="T-2", body={"title": "new"})
        finally:
            await db.close()


def test_sync_write_on_read_only_open_raises_beaver_error(tmp_path):
    path = str(tmp_path / "sealed.db")
    _build(path)

    with _sealed(tmp_path, path), BeaverDB(path, read_only=True) as db:
        with pytest.raises(BeaverReadOnlyError) as exc_info:
            db.dict("settings")["shop"] = "somewhere else"
        assert "read-only" in str(exc_info.value).lower()

        with pytest.raises(BeaverReadOnlyError):
            db.docs("tickets").index(id="T-2", body={"title": "new"})


def test_expired_key_in_read_only_mode_is_not_deleted(tmp_path):
    path = str(tmp_path / "sealed.db")
    with BeaverDB(path) as db:
        db.dict("settings").set("short", "lived", ttl_seconds=0.05)
    time.sleep(0.1)

    with _sealed(tmp_path, path), BeaverDB(path, read_only=True) as db:
        with pytest.raises(KeyError):
            db.dict("settings")["short"]

        assert sorted(os.listdir(tmp_path)) == ["sealed.db"]


def test_reopening_a_current_db_does_not_rewrite_user_version(tmp_path):
    path = str(tmp_path / "versioned.db")
    with BeaverDB(path, pragma_wal=False) as db:
        db.dict("settings")["shop"] = "Spoke & Chain"

    before = Path(path).read_bytes()
    before_mtime = os.stat(path).st_mtime_ns

    with BeaverDB(path, pragma_wal=False) as db:
        assert db.dict("settings")["shop"] == "Spoke & Chain"

    assert Path(path).read_bytes() == before
    assert os.stat(path).st_mtime_ns == before_mtime


async def test_read_only_on_a_missing_file_raises_and_creates_nothing(tmp_path):
    missing = tmp_path / "not-there.db"
    db = AsyncBeaverDB(str(missing), read_only=True)
    with pytest.raises(FileNotFoundError):
        await db.connect()
    assert not missing.exists()


def test_sync_read_only_on_a_missing_file_raises_and_creates_nothing(tmp_path):
    missing = tmp_path / "not-there.db"
    with pytest.raises(FileNotFoundError):
        BeaverDB(str(missing), read_only=True)
    assert not missing.exists()


def test_read_only_memory_database_is_refused():
    with pytest.raises(ValueError):
        BeaverDB(":memory:", read_only=True)

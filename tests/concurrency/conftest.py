"""Concurrency-suite fixtures.

These tests exercise BeaverDB across real OS processes (`multiprocessing`),
so they need a file-backed DB path the children can each open via their own
`aiosqlite` connection. `:memory:` is never shared and would defeat the test.
"""

import os
import uuid

import pytest


@pytest.fixture
def shared_db_path(tmp_path):
    """A file-backed DB path suitable for multi-process access."""
    path = tmp_path / f"concurrency_{uuid.uuid4().hex}.db"
    yield str(path)
    # Best-effort cleanup
    for suffix in ("", "-wal", "-shm"):
        p = str(path) + suffix
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass

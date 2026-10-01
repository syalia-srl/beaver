"""Read-only inspection remains live while another WAL connection writes."""

import pytest

from beaver import AsyncBeaverDB
from beaver.inspection import AsyncBeaverInspector


pytestmark = pytest.mark.unit


async def test_read_only_connection_observes_external_wal_commits(tmp_path):
    path = tmp_path / "live.db"
    writer = await AsyncBeaverDB(str(path)).connect()
    await writer.dict("state").set("version", 1)
    reader = await AsyncBeaverDB(str(path), read_only=True).connect()
    try:
        inspector = AsyncBeaverInspector(reader)
        before = await inspector.info()

        await writer.dict("state").set("version", 2)

        cursor = await reader.connection.execute(
            "SELECT value FROM __beaver_dicts__ WHERE dict_name = ? AND key = ?",
            ("state", "version"),
        )
        assert (await cursor.fetchone())[0] == "2"
        after = await inspector.info()
        assert after.data_version > before.data_version
    finally:
        await reader.close()
        await writer.close()

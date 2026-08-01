import pytest
from beaver import AsyncBeaverDB

pytestmark = pytest.mark.asyncio


async def _tables(db: AsyncBeaverDB) -> set[str]:
    cur = await db.connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )
    return {r[0] for r in await cur.fetchall()}


async def test_field_index_tables_exist(async_db_mem: AsyncBeaverDB):
    names = await _tables(async_db_mem)
    assert "__beaver_field_index__" in names
    assert "__beaver_field_index_manifest__" in names


async def test_field_index_has_expected_columns(async_db_mem: AsyncBeaverDB):
    cur = await async_db_mem.connection.execute(
        "SELECT name FROM pragma_table_info('__beaver_field_index__')"
    )
    cols = {r[0] for r in await cur.fetchall()}
    assert cols == {"kind", "name", "item_key", "field", "value", "value_num"}

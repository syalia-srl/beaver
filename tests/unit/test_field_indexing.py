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


from pydantic import BaseModel
from beaver.indexing import UnindexableFieldError, extract_path, normalize


class Inner(BaseModel):
    name: str


class Item(BaseModel):
    actor: str
    duration_ms: int
    ok: bool
    missing: str | None = None
    tags: list[str] = []
    inner: Inner | None = None


def test_extract_path_flat():
    it = Item(actor="alex", duration_ms=42, ok=True)
    assert extract_path(it, "actor") == (True, "alex")


def test_extract_path_nested():
    it = Item(actor="a", duration_ms=1, ok=True, inner=Inner(name="deep"))
    assert extract_path(it, "inner.name") == (True, "deep")


def test_extract_path_absent_field_is_not_found():
    it = Item(actor="a", duration_ms=1, ok=True)
    assert extract_path(it, "nope") == (False, None)


def test_extract_path_through_none_is_not_found():
    it = Item(actor="a", duration_ms=1, ok=True, inner=None)
    assert extract_path(it, "inner.name") == (False, None)


def test_extract_path_on_plain_dict():
    assert extract_path({"a": {"b": 3}}, "a.b") == (True, 3)


def test_normalize_str_has_no_numeric_form():
    assert normalize("alex") == ("alex", None)


def test_normalize_int_fills_both():
    assert normalize(900) == ("900", 900.0)


def test_normalize_bool_fills_both():
    assert normalize(True) == ("True", 1.0)


def test_normalize_none_is_a_real_indexable_null():
    assert normalize(None) == (None, None)


def test_normalize_rejects_non_scalar():
    with pytest.raises(UnindexableFieldError):
        normalize(["a", "b"])

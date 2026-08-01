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


from beaver.indexing import declare, manifest, mark_complete


async def test_declare_records_fields_as_incomplete(async_db_mem):
    conn = async_db_mem.connection
    await declare(conn, "log", "audit", ["actor", "app"])
    assert await manifest(conn, "log", "audit") == {"actor": False, "app": False}


async def test_mark_complete_flips_only_named_fields(async_db_mem):
    conn = async_db_mem.connection
    await declare(conn, "log", "audit", ["actor", "app"])
    await mark_complete(conn, "log", "audit", ["actor"])
    assert await manifest(conn, "log", "audit") == {"actor": True, "app": False}


async def test_declare_is_idempotent_and_preserves_complete(async_db_mem):
    conn = async_db_mem.connection
    await declare(conn, "log", "audit", ["actor"])
    await mark_complete(conn, "log", "audit", ["actor"])
    await declare(conn, "log", "audit", ["actor", "app"])
    assert await manifest(conn, "log", "audit") == {"actor": True, "app": False}


async def test_manifest_is_scoped_per_collection(async_db_mem):
    conn = async_db_mem.connection
    await declare(conn, "log", "audit", ["actor"])
    await declare(conn, "log", "other", ["thing"])
    assert await manifest(conn, "log", "audit") == {"actor": False}


from beaver.indexing import clear_index, index_item, index_rows, unindex_item


async def _rows(conn, kind, name):
    cur = await conn.execute(
        "SELECT item_key, field, value, value_num FROM __beaver_field_index__ "
        "WHERE kind = ? AND name = ? ORDER BY item_key, field",
        (kind, name),
    )
    return await cur.fetchall()


async def test_index_item_writes_one_row_per_declared_field(async_db_mem):
    conn = async_db_mem.connection
    it = Item(actor="alex", duration_ms=900, ok=True)
    await index_item(conn, "log", "audit", "k1", it, ["actor", "duration_ms"])
    rows = await _rows(conn, "log", "audit")
    assert [(r[1], r[2], r[3]) for r in rows] == [
        ("actor", "alex", None),
        ("duration_ms", "900", 900.0),
    ]


async def test_absent_field_writes_no_row(async_db_mem):
    conn = async_db_mem.connection
    await index_item(
        conn, "log", "audit", "k1", Item(actor="a", duration_ms=1, ok=True), ["nope"]
    )
    assert await _rows(conn, "log", "audit") == []


async def test_reindexing_same_key_replaces_rather_than_duplicates(async_db_mem):
    conn = async_db_mem.connection
    await index_item(
        conn, "log", "audit", "k1", Item(actor="a", duration_ms=1, ok=True), ["actor"]
    )
    await index_item(
        conn, "log", "audit", "k1", Item(actor="b", duration_ms=1, ok=True), ["actor"]
    )
    rows = await _rows(conn, "log", "audit")
    assert len(rows) == 1 and rows[0][2] == "b"


async def test_unindex_item_removes_only_that_item(async_db_mem):
    conn = async_db_mem.connection
    await index_item(
        conn, "log", "audit", "k1", Item(actor="a", duration_ms=1, ok=True), ["actor"]
    )
    await index_item(
        conn, "log", "audit", "k2", Item(actor="b", duration_ms=1, ok=True), ["actor"]
    )
    await unindex_item(conn, "log", "audit", "k1")
    rows = await _rows(conn, "log", "audit")
    assert len(rows) == 1 and rows[0][0] == "k2"


async def test_clear_index_is_scoped_to_one_collection(async_db_mem):
    conn = async_db_mem.connection
    await index_item(
        conn, "log", "a", "k", Item(actor="x", duration_ms=1, ok=True), ["actor"]
    )
    await index_item(
        conn, "log", "b", "k", Item(actor="y", duration_ms=1, ok=True), ["actor"]
    )
    await clear_index(conn, "log", "a")
    assert await _rows(conn, "log", "a") == []
    assert len(await _rows(conn, "log", "b")) == 1


async def test_index_rows_counts_the_collection(async_db_mem):
    conn = async_db_mem.connection
    await index_item(
        conn,
        "log",
        "audit",
        "k1",
        Item(actor="a", duration_ms=1, ok=True),
        ["actor", "duration_ms"],
    )
    assert await index_rows(conn, "log", "audit") == 2


class Event(BaseModel):
    actor: str
    duration_ms: int


async def test_log_write_populates_the_index(async_db_mem):
    log = async_db_mem.log("audit", model=Event, indexed=["actor", "duration_ms"])
    await log.log(Event(actor="alex", duration_ms=900))
    assert await index_rows(async_db_mem.connection, "log", "audit") == 2


async def test_declaration_lands_on_the_first_awaited_operation(async_db_mem):
    """`db.log()` is a synchronous factory, so it cannot write the manifest.
    Declaration lands on the first awaited call. This is safe because an
    absent manifest row falls back to a scan — slower, never wrong."""
    log = async_db_mem.log("audit", model=Event, indexed=["actor"])
    assert await manifest(async_db_mem.connection, "log", "audit") == {}
    await log.log(Event(actor="alex", duration_ms=1))
    assert await manifest(async_db_mem.connection, "log", "audit") == {"actor": False}


async def test_item_key_round_trips_exactly_through_text(async_db_mem):
    """repr(float) round-trips; CAST(x AS TEXT) does not always agree with it.
    Comparing back numerically is what makes the index findable at all."""
    log = async_db_mem.log("audit", model=Event, indexed=["actor"])
    await log.log(Event(actor="alex", duration_ms=1))
    entries = await log.range()
    ts = entries[0].timestamp
    cur = await async_db_mem.connection.execute(
        "SELECT COUNT(*) FROM __beaver_field_index__ "
        "WHERE kind='log' AND name='audit' AND CAST(item_key AS REAL) = ?",
        (ts,),
    )
    assert (await cur.fetchone())[0] == 1


async def test_batched_writes_index_like_individual_ones(async_db_mem):
    log = async_db_mem.log("audit", model=Event, indexed=["actor"])
    async with log.batched() as batch:
        batch.log(Event(actor="a", duration_ms=1))
        batch.log(Event(actor="b", duration_ms=2))
    assert await index_rows(async_db_mem.connection, "log", "audit") == 2


async def test_clear_drops_the_index_too(async_db_mem):
    log = async_db_mem.log("audit", model=Event, indexed=["actor"])
    await log.log(Event(actor="a", duration_ms=1))
    await log.clear()
    assert await index_rows(async_db_mem.connection, "log", "audit") == 0


from beaver.indexing import compile_scan_filters
from beaver import q


def test_compile_scan_filters_emits_json_extract_clauses():
    clauses, params = compile_scan_filters(
        "data", [q(Item).actor == "alex", q(Item).duration_ms > 1000], alias="l"
    )
    assert clauses == [
        "json_extract(l.data, '$.actor') == ?",
        "json_extract(l.data, '$.duration_ms') > ?",
    ]
    assert params == ["alex", 1000]


def test_compile_scan_filters_supports_nested_paths():
    clauses, _ = compile_scan_filters("data", [q(Item).inner.name == "deep"], alias="d")
    assert clauses == ["json_extract(d.data, '$.inner.name') == ?"]

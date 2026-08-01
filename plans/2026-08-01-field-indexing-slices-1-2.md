---
date: 2026-08-01
type: implementation
status: draft
issue: 42
---

# Uniform Field Indexing — Slices 1–2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give `beaver.log()` declared per-field indexing with `where` / `order` /
`offset` on `range()`, backed by a shared substrate that every other collection
can adopt later.

**Architecture:** One new module `beaver/indexing.py` owns everything about the
field index — path extraction, value normalization, the manifest, index-row
maintenance, and filter→SQL compilation. Two new tables carry the index and the
completeness manifest. `logs.py` calls into it; `docs.py` has its inline filter
compiler *extracted* into it (behaviour unchanged) so the two cannot drift.
Everything is additive: no `ALTER TABLE`, no version bump.

**Tech Stack:** Python ≥3.12, aiosqlite, pydantic v2, pytest (`asyncio_mode =
auto`), black.

## Global Constraints

- **`BEAVER_DB_VERSION` stays at `1`** (`beaver/core.py:42`). Do not touch it.
- **No `ALTER TABLE`, ever.** New state goes in new tables created with
  `CREATE TABLE IF NOT EXISTS` inside `_create_all_tables`.
- **All tables use the dunder form** — `__beaver_field_index__`, not
  `beaver_field_index` (`core.py:63`).
- **Core dependencies only:** `aiosqlite`, `numpy`, `pydantic`, `rich`, `typer`.
  No new dependency, and nothing compiled.
- **A query is always correct.** An unindexed or incomplete field falls back to
  the `json_extract` scan. Never return a partial result set.
- **Do not run `make format` or `make bugfix`** — they run `git commit -a` and
  will sweep a concurrent session's files into your commit. Use
  `uv run black .` and stage explicit paths.
- **`make test-unit` depends on `format-check`**, so run `uv run black .` before
  the test step or the run fails on formatting, not on your code.
- Test command throughout: `uv run pytest tests/unit/<file> -v`.

---

## File Structure

| file | responsibility |
|---|---|
| `beaver/indexing.py` **(new)** | The whole field-index substrate: path extraction, value normalization, manifest read/write, index-row maintenance, filter→SQL compilation (both the indexed and the scan form). No knowledge of any specific collection. |
| `beaver/core.py` **(modify)** | Two new tables in `_create_all_tables`; `indexed=` on the `log()` factory; `db.indexes()`. |
| `beaver/manager.py` **(modify)** | `AsyncBeaverBase.__init__` accepts and stores `indexed`. |
| `beaver/logs.py` **(modify)** | Index maintenance on write/clear; `where`/`order`/`offset` on `range()`; `reindex()`, `indexes()`, `explain()`. |
| `beaver/docs.py` **(modify)** | Its inline filter compiler moves to `indexing.py`. Behaviour unchanged — this is a pure refactor guarded by the existing `tests/unit/test_docs.py` and `tests/test_docs_search_filters.py`. |
| `tests/unit/test_field_indexing.py` **(new)** | Substrate + log indexing tests. |

**Slice boundary:** this plan is issue #42 slices **1 and 2** only. Routing
`docs().where()` through the index is slice 3 and is *not* in scope — Task 6
extracts the compiler, but `docs` keeps scanning exactly as it does today.

---

## The one trap to know up front

`__beaver_logs__` keys rows by `timestamp REAL`. The index table keys by
`item_key TEXT`. Converting a float to text and back must round-trip **exactly**,
or a query silently matches nothing.

Python's `repr(float)` is guaranteed to round-trip. SQLite's `CAST(x AS TEXT)`
uses a different formatter and **does not always agree with it**. So:

- **Write** `item_key = repr(ts)` from Python.
- **Query** by casting back to a number: `CAST(item_key AS REAL) = timestamp`.

Never compare `item_key` to `CAST(timestamp AS TEXT)`. Task 5 asserts the
round-trip directly, because this failure mode is invisible — you get zero rows,
not an error.

---

### Task 1: The two tables

**Files:**
- Modify: `beaver/core.py` (in `_create_all_tables`, after the logs block ending ~line 485)
- Test: `tests/unit/test_field_indexing.py`

**Interfaces:**
- Consumes: nothing.
- Produces: tables `__beaver_field_index__` (kind, name, item_key, field, value, value_num) and `__beaver_field_index_manifest__` (kind, name, field, complete).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_field_indexing.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_field_indexing.py -v`
Expected: FAIL — `assert '__beaver_field_index__' in names`

- [ ] **Step 3: Add the tables**

In `beaver/core.py`, immediately after the `idx_logs_timestamp` index creation
(~line 485), insert:

```python
        # Field Index (issue #42) — uniform per-field indexing.
        # Additive by design: new tables only, no ALTER, no version bump.
        await c.execute(
            """
            CREATE TABLE IF NOT EXISTS __beaver_field_index__ (
                kind      TEXT NOT NULL,
                name      TEXT NOT NULL,
                item_key  TEXT NOT NULL,
                field     TEXT NOT NULL,
                value     TEXT,
                value_num REAL,
                PRIMARY KEY (kind, name, item_key, field)
            )
        """
        )
        await c.execute(
            "CREATE INDEX IF NOT EXISTS idx_field_lookup "
            "ON __beaver_field_index__ (kind, name, field, value)"
        )
        await c.execute(
            "CREATE INDEX IF NOT EXISTS idx_field_lookup_num "
            "ON __beaver_field_index__ (kind, name, field, value_num)"
        )
        await c.execute(
            """
            CREATE TABLE IF NOT EXISTS __beaver_field_index_manifest__ (
                kind     TEXT NOT NULL,
                name     TEXT NOT NULL,
                field    TEXT NOT NULL,
                complete INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (kind, name, field)
            )
        """
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run black . && uv run pytest tests/unit/test_field_indexing.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add beaver/core.py tests/unit/test_field_indexing.py
git commit -m "feat(indexing): field index and manifest tables"
```

---

### Task 2: Path extraction and value normalization

**Files:**
- Create: `beaver/indexing.py`
- Test: `tests/unit/test_field_indexing.py`

**Interfaces:**
- Consumes: Task 1's tables (not yet — pure functions).
- Produces: `extract_path(item, path) -> tuple[bool, Any]`, `normalize(value) -> tuple[str | None, float | None]`, `UnindexableFieldError`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_field_indexing.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_field_indexing.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'beaver.indexing'`

- [ ] **Step 3: Write the implementation**

Create `beaver/indexing.py`:

```python
"""Uniform per-field indexing across collections (issue #42).

Owns the whole substrate: dotted-path extraction, scalar normalization, the
completeness manifest, index-row maintenance, and filter -> SQL compilation.
Knows nothing about any specific collection; callers pass their `kind`, `name`
and per-item key.
"""

from typing import Any

from pydantic import BaseModel

from .queries import Filter

INDEX_TABLE = "__beaver_field_index__"
MANIFEST_TABLE = "__beaver_field_index_manifest__"

_MISSING = object()


class UnindexableFieldError(TypeError):
    """Raised when a declared field holds a non-scalar value."""


def extract_path(item: Any, path: str) -> tuple[bool, Any]:
    """Walk a dotted path through models and dicts.

    Returns ``(found, value)``. ``found`` is False when any segment is absent
    or the path runs through a non-traversable value — distinguishing "field
    absent" from "field present and None".
    """
    current: Any = item
    for part in path.split("."):
        if isinstance(current, BaseModel):
            current = getattr(current, part, _MISSING)
        elif isinstance(current, dict):
            current = current.get(part, _MISSING)
        else:
            return False, None
        if current is _MISSING:
            return False, None
    return True, current


def normalize(value: Any) -> tuple[str | None, float | None]:
    """Split a scalar into its (text, numeric) index forms.

    ``value_num`` is what makes ``duration_ms > 1000`` exclude 900; without it
    the comparison is lexicographic and "900" > "1000".
    """
    if value is None:
        return None, None
    if isinstance(value, bool):
        return str(value), float(value)
    if isinstance(value, (int, float)):
        return str(value), float(value)
    if isinstance(value, str):
        return value, None
    raise UnindexableFieldError(
        f"Cannot index a value of type {type(value).__name__}; "
        "only str, int, float, bool and None are indexable."
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run black . && uv run pytest tests/unit/test_field_indexing.py -v`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
git add beaver/indexing.py tests/unit/test_field_indexing.py
git commit -m "feat(indexing): dotted-path extraction and scalar normalization"
```

---

### Task 3: The completeness manifest

**Files:**
- Modify: `beaver/indexing.py`
- Test: `tests/unit/test_field_indexing.py`

**Interfaces:**
- Consumes: `INDEX_TABLE`, `MANIFEST_TABLE` from Task 2.
- Produces: `async declare(conn, kind, name, fields) -> None`, `async manifest(conn, kind, name) -> dict[str, bool]`, `async mark_complete(conn, kind, name, fields) -> None`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_field_indexing.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_field_indexing.py -v`
Expected: FAIL — `ImportError: cannot import name 'declare'`

- [ ] **Step 3: Write the implementation**

Append to `beaver/indexing.py`:

```python
async def declare(conn, kind: str, name: str, fields: list[str]) -> None:
    """Record fields as declared. Idempotent, and never downgrades `complete`.

    Re-declaring an already-complete field must not reset it, or every process
    restart would silently drop the collection back to scanning.
    """
    await conn.executemany(
        f"INSERT OR IGNORE INTO {MANIFEST_TABLE} (kind, name, field, complete) "
        "VALUES (?, ?, ?, 0)",
        [(kind, name, f) for f in fields],
    )


async def manifest(conn, kind: str, name: str) -> dict[str, bool]:
    """Map declared field -> whether the read path may trust its index."""
    cursor = await conn.execute(
        f"SELECT field, complete FROM {MANIFEST_TABLE} WHERE kind = ? AND name = ?",
        (kind, name),
    )
    return {row[0]: bool(row[1]) for row in await cursor.fetchall()}


async def mark_complete(conn, kind: str, name: str, fields: list[str]) -> None:
    """Mark fields as fully backfilled, so queries may use the index."""
    await conn.executemany(
        f"UPDATE {MANIFEST_TABLE} SET complete = 1 "
        "WHERE kind = ? AND name = ? AND field = ?",
        [(kind, name, f) for f in fields],
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run black . && uv run pytest tests/unit/test_field_indexing.py -v`
Expected: 16 passed

- [ ] **Step 5: Commit**

```bash
git add beaver/indexing.py tests/unit/test_field_indexing.py
git commit -m "feat(indexing): completeness manifest"
```

---

### Task 4: Index-row maintenance

**Files:**
- Modify: `beaver/indexing.py`
- Test: `tests/unit/test_field_indexing.py`

**Interfaces:**
- Consumes: `extract_path`, `normalize` (Task 2).
- Produces: `async index_item(conn, kind, name, item_key, item, fields) -> None`, `async unindex_item(conn, kind, name, item_key) -> None`, `async clear_index(conn, kind, name) -> None`, `async index_rows(conn, kind, name) -> int`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_field_indexing.py`:

```python
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
    await index_item(conn, "log", "audit", "k1", Item(actor="a", duration_ms=1, ok=True), ["nope"])
    assert await _rows(conn, "log", "audit") == []


async def test_reindexing_same_key_replaces_rather_than_duplicates(async_db_mem):
    conn = async_db_mem.connection
    await index_item(conn, "log", "audit", "k1", Item(actor="a", duration_ms=1, ok=True), ["actor"])
    await index_item(conn, "log", "audit", "k1", Item(actor="b", duration_ms=1, ok=True), ["actor"])
    rows = await _rows(conn, "log", "audit")
    assert len(rows) == 1 and rows[0][2] == "b"


async def test_unindex_item_removes_only_that_item(async_db_mem):
    conn = async_db_mem.connection
    await index_item(conn, "log", "audit", "k1", Item(actor="a", duration_ms=1, ok=True), ["actor"])
    await index_item(conn, "log", "audit", "k2", Item(actor="b", duration_ms=1, ok=True), ["actor"])
    await unindex_item(conn, "log", "audit", "k1")
    rows = await _rows(conn, "log", "audit")
    assert len(rows) == 1 and rows[0][0] == "k2"


async def test_clear_index_is_scoped_to_one_collection(async_db_mem):
    conn = async_db_mem.connection
    await index_item(conn, "log", "a", "k", Item(actor="x", duration_ms=1, ok=True), ["actor"])
    await index_item(conn, "log", "b", "k", Item(actor="y", duration_ms=1, ok=True), ["actor"])
    await clear_index(conn, "log", "a")
    assert await _rows(conn, "log", "a") == []
    assert len(await _rows(conn, "log", "b")) == 1


async def test_index_rows_counts_the_collection(async_db_mem):
    conn = async_db_mem.connection
    await index_item(conn, "log", "audit", "k1", Item(actor="a", duration_ms=1, ok=True), ["actor", "duration_ms"])
    assert await index_rows(conn, "log", "audit") == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_field_indexing.py -v`
Expected: FAIL — `ImportError: cannot import name 'index_item'`

- [ ] **Step 3: Write the implementation**

Append to `beaver/indexing.py`:

```python
def build_rows(
    kind: str, name: str, item_key: str, item: Any, fields: list[str]
) -> list[tuple]:
    """The index rows for one item. Absent fields produce no row."""
    rows: list[tuple] = []
    for field in fields:
        found, raw = extract_path(item, field)
        if not found:
            continue
        value, value_num = normalize(raw)
        rows.append((kind, name, item_key, field, value, value_num))
    return rows


async def index_item(
    conn, kind: str, name: str, item_key: str, item: Any, fields: list[str]
) -> None:
    """Replace this item's index rows. Delete-then-insert so an overwrite
    cannot leave a stale row behind for a field that is now absent."""
    await unindex_item(conn, kind, name, item_key)
    rows = build_rows(kind, name, item_key, item, fields)
    if rows:
        await conn.executemany(
            f"INSERT INTO {INDEX_TABLE} "
            "(kind, name, item_key, field, value, value_num) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )


async def unindex_item(conn, kind: str, name: str, item_key: str) -> None:
    await conn.execute(
        f"DELETE FROM {INDEX_TABLE} WHERE kind = ? AND name = ? AND item_key = ?",
        (kind, name, item_key),
    )


async def clear_index(conn, kind: str, name: str) -> None:
    await conn.execute(
        f"DELETE FROM {INDEX_TABLE} WHERE kind = ? AND name = ?", (kind, name)
    )


async def index_rows(conn, kind: str, name: str) -> int:
    cursor = await conn.execute(
        f"SELECT COUNT(*) FROM {INDEX_TABLE} WHERE kind = ? AND name = ?",
        (kind, name),
    )
    row = await cursor.fetchone()
    return row[0] if row else 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run black . && uv run pytest tests/unit/test_field_indexing.py -v`
Expected: 22 passed

- [ ] **Step 5: Commit**

```bash
git add beaver/indexing.py tests/unit/test_field_indexing.py
git commit -m "feat(indexing): index-row maintenance"
```

---

### Task 5: Declare `indexed=` on logs and maintain the index on write

**Files:**
- Modify: `beaver/manager.py:23-42` (`AsyncBeaverBase.__init__`)
- Modify: `beaver/core.py:687-690` (the `log()` factory)
- Modify: `beaver/logs.py` (`AsyncBeaverLog.log`, `clear`, `AsyncLogBatch.__aexit__`)
- Test: `tests/unit/test_field_indexing.py`

**Interfaces:**
- Consumes: `declare`, `index_item`, `clear_index` (Tasks 3–4).
- Produces: `db.log(name, model=…, indexed=[…])`; `AsyncBeaverBase._indexed: list[str]`; log rows indexed under `kind="log"` with `item_key = repr(timestamp)`.

> ⚠️ **`singleton()` ignores kwargs on a cache hit** (`core.py:634-646`): the
> cache key is `(cls, name)` only, so after a bare `db.log("audit")` a later
> `db.log("audit", indexed=["actor"])` returns the **already-cached, undeclared**
> manager and the declaration is silently dropped. This predates the plan and is
> not fixed here, but it is why Task 9's test clears `_manager_cache` to
> re-open a log with a declaration. Document it in the `indexed=` docstring —
> "declare on first use" — and file a follow-up issue to make `singleton()`
> reject or honour differing kwargs. A declaration that quietly does nothing is
> the failure mode issue #41 warns about.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_field_indexing.py`:

```python
class Event(BaseModel):
    actor: str
    duration_ms: int


async def test_log_write_populates_the_index(async_db_mem):
    log = async_db_mem.log("audit", model=Event, indexed=["actor", "duration_ms"])
    await log.log(Event(actor="alex", duration_ms=900))
    assert await index_rows(async_db_mem.connection, "log", "audit") == 2


async def test_declaring_records_an_incomplete_manifest(async_db_mem):
    async_db_mem.log("audit", model=Event, indexed=["actor"])
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_field_indexing.py -v`
Expected: FAIL — `TypeError: log() got an unexpected keyword argument 'indexed'`

- [ ] **Step 3: Write the implementation**

In `beaver/manager.py`, change the `AsyncBeaverBase.__init__` signature and add
one attribute:

```python
    def __init__(
        self,
        name: str,
        db: "AsyncBeaverDB",
        model: Type[T] | None = None,
        indexed: list[str] | None = None,
    ):
```

and after `self._model = model` (line 38) add:

```python
        self._indexed: list[str] = list(indexed or [])
```

In `beaver/core.py`, change the `log()` factory:

```python
    def log[T: BaseModel](
        self,
        name: str,
        model: type[T] | None = None,
        indexed: list[str] | None = None,
    ) -> AsyncBeaverLog[T]:
        return self.singleton(AsyncBeaverLog, name, model=model, indexed=indexed)
```

In `beaver/logs.py`, add the import and a small helper near the top:

```python
from . import indexing
```

Add to `AsyncBeaverLog` a declaration hook and the item-key rule:

```python
    _INDEX_KIND = "log"

    @staticmethod
    def _item_key(ts: float) -> str:
        """repr() round-trips a float exactly; SQLite's CAST(x AS TEXT) does
        not always agree with it. Queries must compare CAST(item_key AS REAL)
        back to the timestamp, never text to text."""
        return repr(ts)

    async def _ensure_declared(self) -> None:
        if self._indexed and not getattr(self, "_declared", False):
            await indexing.declare(
                self.connection, self._INDEX_KIND, self._name, self._indexed
            )
            self._declared = True
```

In `AsyncBeaverLog.log`, after the `break` that ends the insert retry loop, add:

```python
        if self._indexed:
            await self._ensure_declared()
            await indexing.index_item(
                self.connection,
                self._INDEX_KIND,
                self._name,
                self._item_key(ts),
                data,
                self._indexed,
            )
```

In `AsyncBeaverLog.clear`, after the existing `DELETE`:

```python
        await indexing.clear_index(self.connection, self._INDEX_KIND, self._name)
```

In `AsyncLogBatch.__aexit__`, after the existing `executemany` that flushes
`self._pending`, add:

```python
        mgr = self._manager
        if mgr._indexed:
            await mgr._ensure_declared()
            for _name, ts, _payload, item in self._pending_items:
                await indexing.index_item(
                    mgr.connection,
                    mgr._INDEX_KIND,
                    mgr._name,
                    mgr._item_key(ts),
                    item,
                    mgr._indexed,
                )
```

`AsyncLogBatch.log` currently keeps only the serialized tuple. Keep the original
object alongside it so the batch can index without re-parsing — in
`AsyncLogBatch.__init__` add `self._pending_items: list[tuple] = []`, and in
`AsyncLogBatch.log`, after the existing `self._pending.append(...)`, add:

```python
        self._pending_items.append((self._manager._name, ts, None, data))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run black . && uv run pytest tests/unit/test_field_indexing.py tests/unit/test_logs.py tests/unit/test_batched.py -v`
Expected: all pass — the existing log and batch suites must stay green, since an
undeclared log takes the same path it always did.

- [ ] **Step 5: Commit**

```bash
git add beaver/manager.py beaver/core.py beaver/logs.py tests/unit/test_field_indexing.py
git commit -m "feat(logs): indexed= declaration and index maintenance on write"
```

---

### Task 6: Extract the filter compiler out of `docs.py`

**Files:**
- Modify: `beaver/indexing.py`
- Modify: `beaver/docs.py:470-476` (the `q._filters` loop in `_execute_query`)
- Test: existing `tests/unit/test_docs.py`, `tests/test_docs_search_filters.py`

**Interfaces:**
- Consumes: `Filter` from `beaver/queries.py`.
- Produces: `compile_scan_filters(column, filters, alias) -> tuple[list[str], list]`.

This is a **pure refactor**. `docs` keeps scanning exactly as before; the point
is that one compiler now serves both consumers so they cannot drift. Routing
`docs` through the index is slice 3, not this plan.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_field_indexing.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_field_indexing.py -v`
Expected: FAIL — `ImportError: cannot import name 'compile_scan_filters'`

- [ ] **Step 3: Write the implementation**

Append to `beaver/indexing.py`:

```python
def compile_scan_filters(
    column: str, filters: list[Filter], alias: str = "d"
) -> tuple[list[str], list]:
    """Compile filters to json_extract predicates — the unindexed fallback.

    Correct for any field, indexed or not, which is what lets an incomplete
    index degrade to something slower instead of something wrong.
    """
    clauses: list[str] = []
    params: list = []
    for f in filters:
        clauses.append(f"json_extract({alias}.{column}, '$.{f.path}') {f.operator} ?")
        params.append(f.value)
    return clauses, params
```

In `beaver/docs.py`, replace the inline loop (lines 470-476):

```python
        if q._filters:
            for filter in q._filters:
                where.append(
                    f"json_extract(d.data, '$.{filter.path}') {filter.operator} ?"
                )
                params.append(filter.value)
```

with:

```python
        if q._filters:
            clauses, filter_params = indexing.compile_scan_filters(
                "data", q._filters, alias="d"
            )
            where.extend(clauses)
            params.extend(filter_params)
```

and add `from . import indexing` to the imports at the top of `docs.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run black . && uv run pytest tests/unit/test_field_indexing.py tests/unit/test_docs.py tests/test_docs_search_filters.py -v`
Expected: all pass. The docs suites are the real gate here — they prove the
refactor changed nothing.

- [ ] **Step 5: Commit**

```bash
git add beaver/indexing.py beaver/docs.py tests/unit/test_field_indexing.py
git commit -m "refactor(indexing): one filter compiler shared by docs and logs"
```

---

### Task 7: `where=` on `log.range()`

**Files:**
- Modify: `beaver/indexing.py`
- Modify: `beaver/logs.py:106-137` (`range`)
- Test: `tests/unit/test_field_indexing.py`

**Interfaces:**
- Consumes: `manifest` (Task 3), `compile_scan_filters` (Task 6).
- Produces: `compile_indexed_filter(kind, name, f, key_expr) -> tuple[str, list]`; `log.range(where=[...])`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_field_indexing.py`:

```python
async def _seed(db, indexed):
    log = db.log("audit", model=Event, indexed=indexed)
    await log.log(Event(actor="alex", duration_ms=900))
    await log.log(Event(actor="alex", duration_ms=2000))
    await log.log(Event(actor="yudi", duration_ms=50))
    return log


async def test_where_filters_by_equality_when_indexed(async_db_mem):
    log = await _seed(async_db_mem, ["actor", "duration_ms"])
    await log.reindex()
    rows = await log.range(where=[q(Event).actor == "alex"])
    assert {r.data.duration_ms for r in rows} == {900, 2000}


async def test_where_is_correct_without_any_index(async_db_mem):
    """The fallback path must return the same rows, just slower."""
    log = await _seed(async_db_mem, [])
    rows = await log.range(where=[q(Event).actor == "alex"])
    assert {r.data.duration_ms for r in rows} == {900, 2000}


async def test_where_is_correct_while_the_index_is_incomplete(async_db_mem):
    """Declared but never reindexed: must not silently return a subset."""
    log = async_db_mem.log("audit", model=Event, indexed=["actor"])
    await log.log(Event(actor="alex", duration_ms=900))
    await async_db_mem.connection.execute(
        "DELETE FROM __beaver_field_index__"
    )  # simulate rows written before declaration
    rows = await log.range(where=[q(Event).actor == "alex"])
    assert len(rows) == 1


async def test_numeric_comparison_does_not_compare_as_text(async_db_mem):
    log = await _seed(async_db_mem, ["duration_ms"])
    await log.reindex()
    rows = await log.range(where=[q(Event).duration_ms > 1000])
    assert [r.data.duration_ms for r in rows] == [2000]


async def test_multiple_filters_intersect(async_db_mem):
    log = await _seed(async_db_mem, ["actor", "duration_ms"])
    await log.reindex()
    rows = await log.range(
        where=[q(Event).actor == "alex", q(Event).duration_ms > 1000]
    )
    assert [r.data.duration_ms for r in rows] == [2000]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_field_indexing.py -v`
Expected: FAIL — `TypeError: range() got an unexpected keyword argument 'where'`

- [ ] **Step 3: Write the implementation**

Append to `beaver/indexing.py`:

```python
_NUMERIC_OPS = {">", ">=", "<", "<="}


def compile_indexed_filter(
    kind: str, name: str, f: Filter, key_expr: str
) -> tuple[str, list]:
    """One filter as a membership test against the field index.

    ``key_expr`` is how the outer table's row identity is written in SQL —
    for logs, ``timestamp``, compared against ``CAST(item_key AS REAL)``.
    """
    column = "value_num" if f.operator in _NUMERIC_OPS else "value"
    value = float(f.value) if f.operator in _NUMERIC_OPS else f.value
    sql = (
        f"{key_expr} IN (SELECT CAST(item_key AS REAL) FROM {INDEX_TABLE} "
        f"WHERE kind = ? AND name = ? AND field = ? AND {column} {f.operator} ?)"
    )
    return sql, [kind, name, f.path, value]


def plan_filters(
    kind: str,
    name: str,
    filters: list[Filter],
    complete: dict[str, bool],
    key_expr: str,
    column: str,
    alias: str,
) -> tuple[list[str], list, list[str], list[str]]:
    """Split filters into indexed and scanned, and compile both.

    Returns ``(clauses, params, indexed_paths, scanned_paths)``. A field is only
    routed to the index when the manifest says it is complete — an unbackfilled
    index would answer with a subset and say nothing about it.
    """
    clauses: list[str] = []
    params: list = []
    indexed: list[str] = []
    scanned: list[str] = []
    for f in filters:
        if complete.get(f.path):
            sql, ps = compile_indexed_filter(kind, name, f, key_expr)
            clauses.append(sql)
            params.extend(ps)
            indexed.append(f.path)
        else:
            sql_list, ps = compile_scan_filters(column, [f], alias=alias)
            clauses.extend(sql_list)
            params.extend(ps)
            scanned.append(f.path)
    return clauses, params, indexed, scanned
```

In `beaver/logs.py`, rewrite `range` to build its WHERE from the plan. Replace
the body up to the `ORDER BY` line with:

```python
    async def range(
        self,
        start: float | None = None,
        end: float | None = None,
        limit: int | None = None,
        where: list | None = None,
    ) -> list[LogEntry[T]]:
        """
        Retrieves a list of log entries within a time range.
        """
        query = (
            "SELECT timestamp, data FROM __beaver_logs__ AS l WHERE log_name = ?"
        )
        params: list = [self._name]

        if start is not None:
            query += " AND timestamp >= ?"
            params.append(start)

        if end is not None:
            query += " AND timestamp <= ?"
            params.append(end)

        if where:
            complete = await indexing.manifest(
                self.connection, self._INDEX_KIND, self._name
            )
            clauses, filter_params, _, _ = indexing.plan_filters(
                self._INDEX_KIND,
                self._name,
                where,
                complete,
                key_expr="l.timestamp",
                column="data",
                alias="l",
            )
            for clause in clauses:
                query += f" AND {clause}"
            params.extend(filter_params)

        query += " ORDER BY timestamp ASC"

        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
```

(The rest of the method — `execute`, `fetchall`, the `LogEntry` comprehension —
is unchanged. Note the table now carries the alias `l`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run black . && uv run pytest tests/unit/test_field_indexing.py tests/unit/test_logs.py -v`
Expected: all pass. `test_where_is_correct_without_any_index` and
`…_while_the_index_is_incomplete` are the ones that matter — they prove the
fallback, which is what makes this safe on an existing database.

- [ ] **Step 5: Commit**

```bash
git add beaver/indexing.py beaver/logs.py tests/unit/test_field_indexing.py
git commit -m "feat(logs): where= on range(), indexed with a correct scan fallback"
```

---

### Task 8: `order=` and `offset=` on `log.range()`

**Files:**
- Modify: `beaver/logs.py` (`range`)
- Test: `tests/unit/test_field_indexing.py`

**Interfaces:**
- Consumes: Task 7's `range`.
- Produces: `range(order: str = "ASC", offset: int | None = None)`.

- [ ] **Step 1: Write the failing test**

```python
async def test_order_desc_returns_newest_first(async_db_mem):
    log = await _seed(async_db_mem, [])
    rows = await log.range(order="DESC")
    assert [r.data.actor for r in rows] == ["yudi", "alex", "alex"]


async def test_offset_paginates(async_db_mem):
    log = await _seed(async_db_mem, [])
    page = await log.range(order="ASC", limit=1, offset=1)
    assert len(page) == 1 and page[0].data.duration_ms == 2000


async def test_order_rejects_anything_but_asc_desc(async_db_mem):
    log = await _seed(async_db_mem, [])
    with pytest.raises(ValueError):
        await log.range(order="ASC; DROP TABLE __beaver_logs__")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_field_indexing.py -v`
Expected: FAIL — `TypeError: range() got an unexpected keyword argument 'order'`

- [ ] **Step 3: Write the implementation**

Add the two parameters to `range`'s signature (after `where`):

```python
        order: str = "ASC",
        offset: int | None = None,
```

Replace the hardcoded `ORDER BY` and the `LIMIT` block with:

```python
        direction = order.upper()
        if direction not in ("ASC", "DESC"):
            raise ValueError(
                f"order must be 'ASC' or 'DESC', got {order!r}"
            )
        query += f" ORDER BY timestamp {direction}"

        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)

        if offset is not None:
            # SQLite requires LIMIT before OFFSET; -1 means "no limit".
            if limit is None:
                query += " LIMIT -1"
            query += " OFFSET ?"
            params.append(offset)
```

The `order` value is interpolated, not parameterized — SQL placeholders cannot
carry a keyword — which is exactly why the whitelist check above must come
first.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run black . && uv run pytest tests/unit/test_field_indexing.py tests/unit/test_logs.py -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add beaver/logs.py tests/unit/test_field_indexing.py
git commit -m "feat(logs): order= and offset= on range()"
```

---

### Task 9: `reindex()`

**Files:**
- Modify: `beaver/logs.py`
- Test: `tests/unit/test_field_indexing.py`

**Interfaces:**
- Consumes: `index_item`, `mark_complete`, `declare`.
- Produces: `async log.reindex(fields: list[str] | None = None) -> int` (rows written).

- [ ] **Step 1: Write the failing test**

```python
async def test_reindex_backfills_rows_written_before_declaration(async_db_mem):
    plain = async_db_mem.log("hist", model=Event)
    await plain.log(Event(actor="alex", duration_ms=5))
    async_db_mem._manager_cache.clear()  # reopen the log with a declaration
    log = async_db_mem.log("hist", model=Event, indexed=["actor"])
    assert await index_rows(async_db_mem.connection, "log", "hist") == 0
    written = await log.reindex()
    assert written == 1
    assert await manifest(async_db_mem.connection, "log", "hist") == {"actor": True}


async def test_reindex_does_not_change_results_only_the_plan(async_db_mem):
    log = await _seed(async_db_mem, ["actor"])
    before = [r.data.duration_ms for r in await log.range(where=[q(Event).actor == "alex"])]
    await log.reindex()
    after = [r.data.duration_ms for r in await log.range(where=[q(Event).actor == "alex"])]
    assert before == after


async def test_reindex_subset_marks_only_those_fields_complete(async_db_mem):
    log = await _seed(async_db_mem, ["actor", "duration_ms"])
    await log.reindex(["actor"])
    assert await manifest(async_db_mem.connection, "log", "audit") == {
        "actor": True,
        "duration_ms": False,
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_field_indexing.py -v`
Expected: FAIL — `AttributeError: 'AsyncBeaverLog' object has no attribute 'reindex'`

- [ ] **Step 3: Write the implementation**

Add to `AsyncBeaverLog`, with the `@local_only` guard the other scan-the-world
methods carry:

```python
    @local_only("reindex() rewrites the local index and is not exposed remotely")
    async def reindex(self, fields: list[str] | None = None) -> int:
        """Backfill the field index for this log and mark those fields complete.

        Not run automatically on open: backfilling a large log is real work, and
        doing it silently inside connect() turns opening a database into a stall
        nobody asked for.
        """
        target = list(fields) if fields else list(self._indexed)
        if not target:
            return 0
        await indexing.declare(
            self.connection, self._INDEX_KIND, self._name, target
        )
        written = 0
        for entry in await self.range():
            await indexing.index_item(
                self.connection,
                self._INDEX_KIND,
                self._name,
                self._item_key(entry.timestamp),
                entry.data,
                target,
            )
            written += 1
        await indexing.mark_complete(
            self.connection, self._INDEX_KIND, self._name, target
        )
        return written
```

Note `reindex()` calls `self.range()` with no `where`, so it takes the plain
time-ordered path and cannot recurse into the planner.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run black . && uv run pytest tests/unit/test_field_indexing.py -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add beaver/logs.py tests/unit/test_field_indexing.py
git commit -m "feat(logs): reindex() backfills and marks fields complete"
```

---

### Task 10: Introspection — `indexes()`, `db.indexes()`, `explain()`

**Files:**
- Modify: `beaver/indexing.py` (the `FieldIndex` / `QueryPlan` dataclasses)
- Modify: `beaver/logs.py` (`indexes`, `explain`)
- Modify: `beaver/core.py` (`AsyncBeaverDB.indexes`)
- Test: `tests/unit/test_field_indexing.py`

**Interfaces:**
- Consumes: `manifest`, `plan_filters`.
- Produces: `FieldIndex(field, declared, complete, rows)`, `QueryPlan(indexed, scanned, estimated_rows)`, `async log.indexes() -> list[FieldIndex]`, `async log.explain(where) -> QueryPlan`, `async db.indexes() -> dict[tuple[str, str], list[FieldIndex]]`.

- [ ] **Step 1: Write the failing test**

```python
from beaver.indexing import FieldIndex, QueryPlan


async def test_indexes_reports_incomplete_before_reindex(async_db_mem):
    log = await _seed(async_db_mem, ["actor"])
    await async_db_mem.connection.execute("DELETE FROM __beaver_field_index__")
    [fi] = await log.indexes()
    assert fi.field == "actor" and fi.declared and not fi.complete and fi.rows == 0


async def test_indexes_reports_complete_after_reindex(async_db_mem):
    log = await _seed(async_db_mem, ["actor"])
    await log.reindex()
    [fi] = await log.indexes()
    assert fi.complete and fi.rows == 3


async def test_explain_names_indexed_and_scanned_fields(async_db_mem):
    log = await _seed(async_db_mem, ["actor"])
    await log.reindex()
    plan = await log.explain(
        where=[q(Event).actor == "alex", q(Event).duration_ms > 10]
    )
    assert plan.indexed == ["actor"]
    assert plan.scanned == ["duration_ms"]


async def test_db_indexes_lists_every_collection(async_db_mem):
    a = async_db_mem.log("a", model=Event, indexed=["actor"])
    await a.log(Event(actor="x", duration_ms=1))
    b = async_db_mem.log("b", model=Event, indexed=["duration_ms"])
    await b.log(Event(actor="y", duration_ms=2))
    everything = await async_db_mem.indexes()
    assert set(everything) == {("log", "a"), ("log", "b")}
    assert [f.field for f in everything[("log", "a")]] == ["actor"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_field_indexing.py -v`
Expected: FAIL — `ImportError: cannot import name 'FieldIndex'`

- [ ] **Step 3: Write the implementation**

Add to the top of `beaver/indexing.py` (after the imports):

```python
from dataclasses import dataclass, field as _dc_field


@dataclass
class FieldIndex:
    """The state of one declared field.

    `declared` says the write path maintains it; `complete` says the read path
    may trust it. They are different questions and both matter.
    """

    field: str
    declared: bool
    complete: bool
    rows: int


@dataclass
class QueryPlan:
    """Which filters resolved by index and which fell back to a scan."""

    indexed: list[str] = _dc_field(default_factory=list)
    scanned: list[str] = _dc_field(default_factory=list)
    estimated_rows: int = 0
```

And a shared collector:

```python
async def field_indexes(conn, kind: str, name: str) -> list[FieldIndex]:
    declared = await manifest(conn, kind, name)
    cursor = await conn.execute(
        f"SELECT field, COUNT(*) FROM {INDEX_TABLE} "
        "WHERE kind = ? AND name = ? GROUP BY field",
        (kind, name),
    )
    counts = {row[0]: row[1] for row in await cursor.fetchall()}
    return [
        FieldIndex(field=f, declared=True, complete=c, rows=counts.get(f, 0))
        for f, c in sorted(declared.items())
    ]


async def all_field_indexes(conn) -> dict[tuple[str, str], list[FieldIndex]]:
    cursor = await conn.execute(
        f"SELECT DISTINCT kind, name FROM {MANIFEST_TABLE} ORDER BY kind, name"
    )
    pairs = [(r[0], r[1]) for r in await cursor.fetchall()]
    return {(k, n): await field_indexes(conn, k, n) for k, n in pairs}
```

Add to `AsyncBeaverLog`:

```python
    @expose(
        path="/indexes",
        method="GET",
        cli_name="indexes",
        cli_help="Show declared field indexes and whether they are complete.",
    )
    async def indexes(self) -> list[indexing.FieldIndex]:
        """The declared fields, whether each is trusted, and its row count."""
        await self._ensure_declared()
        return await indexing.field_indexes(
            self.connection, self._INDEX_KIND, self._name
        )

    @expose(
        path="/explain",
        method="POST",
        cli_name="explain",
        cli_help="Show which filters would use the index and which would scan.",
    )
    async def explain(self, where: list) -> indexing.QueryPlan:
        """Which filters resolve by index and which fall back to a scan.

        Without this the fallback is invisible: a query that quietly degraded
        looks exactly like one that used the index, only slower.
        """
        await self._ensure_declared()
        complete = await indexing.manifest(
            self.connection, self._INDEX_KIND, self._name
        )
        _, _, indexed, scanned = indexing.plan_filters(
            self._INDEX_KIND,
            self._name,
            where,
            complete,
            key_expr="l.timestamp",
            column="data",
            alias="l",
        )
        return indexing.QueryPlan(
            indexed=indexed, scanned=scanned, estimated_rows=await self.count()
        )
```

Add to `AsyncBeaverDB` in `beaver/core.py`, next to the factory methods:

```python
    async def indexes(self) -> dict:
        """Every declared field index in this database, by (kind, name)."""
        from . import indexing

        return await indexing.all_field_indexes(self.connection)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run black . && uv run pytest tests/unit/test_field_indexing.py tests/unit/test_api_expose.py -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add beaver/indexing.py beaver/logs.py beaver/core.py tests/unit/test_field_indexing.py
git commit -m "feat(indexing): indexes(), db.indexes() and explain()"
```

---

### Task 11: The additivity guarantee

**Files:**
- Test: `tests/unit/test_field_indexing.py`

**Interfaces:**
- Consumes: everything above.
- Produces: nothing — this task exists to make §4 of the issue a tested claim rather than a written one.

- [ ] **Step 1: Write the failing test**

```python
import os
import uuid
from beaver.core import BEAVER_DB_VERSION, AsyncBeaverDB


async def test_existing_database_gains_the_tables_without_a_version_bump(tmp_path):
    """An unmigrated file must open, gain the new tables, and keep its
    user_version — that is the whole no-migration promise."""
    path = str(tmp_path / f"legacy_{uuid.uuid4().hex}.db")

    db = AsyncBeaverDB(path)
    await db.connect()
    log = db.log("audit", model=Event)
    await log.log(Event(actor="alex", duration_ms=1))
    # Simulate a file written before this feature existed.
    await db.connection.execute("DROP TABLE __beaver_field_index__")
    await db.connection.execute("DROP TABLE __beaver_field_index_manifest__")
    await db.connection.commit()
    await db.close()

    db2 = AsyncBeaverDB(path)
    await db2.connect()
    cur = await db2.connection.execute("PRAGMA user_version")
    assert (await cur.fetchone())[0] == BEAVER_DB_VERSION == 1

    names = await _tables(db2)
    assert "__beaver_field_index__" in names

    # The pre-existing row is still readable and still findable by filter,
    # via the scan fallback, with no reindex.
    log2 = db2.log("audit", model=Event, indexed=["actor"])
    rows = await log2.range(where=[q(Event).actor == "alex"])
    assert len(rows) == 1
    await db2.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_field_indexing.py::test_existing_database_gains_the_tables_without_a_version_bump -v`
Expected: PASS if Tasks 1–10 are correct. **If it fails, that is the bug** — do
not adjust the test to match the code.

Then mutation-check the gate: temporarily change `BEAVER_DB_VERSION` to `2` in
`beaver/core.py:42`, re-run, and confirm the test **fails**. Revert. A guarantee
test that cannot fail is worth less than none.

- [ ] **Step 3: No implementation**

If Step 2 passed on the first run and failed under the mutation, there is nothing
to write. If it failed, fix the code in the task that broke additivity.

- [ ] **Step 4: Run the whole suite**

Run: `uv run black . && make test-unit`
Expected: the full unit suite green, including the 38 pre-existing files.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_field_indexing.py
git commit -m "test(indexing): additivity is a tested guarantee, not a claim"
```

---

### Task 12: Release

**Files:**
- Modify: `issues/42-uniform-field-indexing-across-collections.md` (status)
- Modify: `STATUS.md`

**Interfaces:**
- Consumes: Tasks 1–11.
- Produces: `beaver-db` 2.3.0 on PyPI, which `repos/ainbox` will pin.

- [ ] **Step 1: Update the issue and STATUS**

In `issues/42-…md` frontmatter, leave `state: open` (slices 3–6 remain) and add
a line at the top of §6 Delivery order recording that slices 1–2 landed in 2.3.0.

Add a row to the `STATUS.md` feature table:

```markdown
| Field indexing on logs (#42 slices 1–2) | ✅ | `indexing.py`; `indexed=`, `where`/`order`/`offset`, `reindex()`, `indexes()`, `explain()`. docs/blobs/vectors pending (slices 3–6) |
```

- [ ] **Step 2: Run the full suite**

Run: `uv run black . && make test-all`
Expected: unit + integration + concurrency green.

- [ ] **Step 3: Commit the docs**

```bash
git add issues/42-uniform-field-indexing-across-collections.md STATUS.md
git commit -m "docs: field indexing slices 1-2 landed"
```

- [ ] **Step 4: Release**

Run: `NEW_VERSION=2.3.0 make release`

This runs `test-all`, bumps `pyproject.toml` *and* `beaver/__init__.py`, commits,
tags `v2.3.0`, pushes, and opens the GitHub release. Do not hand-edit the version
strings.

- [ ] **Step 5: Verify the artifact, not a proxy**

Do not trust the tag. In a scratch directory, install the **published** package
and exercise the feature through it:

```bash
cd /tmp && uv venv verify-beaver && \
  VIRTUAL_ENV=/tmp/verify-beaver uv pip install "beaver-db==2.3.0" && \
  VIRTUAL_ENV=/tmp/verify-beaver uv run python -c "
import asyncio, beaver
from pydantic import BaseModel
from beaver.core import AsyncBeaverDB
class E(BaseModel):
    actor: str
async def main():
    async with AsyncBeaverDB(':memory:') as db:
        log = db.log('a', model=E, indexed=['actor'])
        await log.log(E(actor='alex'))
        await log.reindex()
        print(await log.indexes())
        print(len(await log.range(where=[beaver.q(E).actor == 'alex'])))
asyncio.run(main())
"
```

Expected: one `FieldIndex(field='actor', declared=True, complete=True, rows=1)`
and `1`. If PyPI has not propagated yet, wait and retry — do not conclude success
from the tag existing.

---

## Self-Review

**Spec coverage (issue #42 slices 1–2):**

| spec section | task |
|---|---|
| §3.1 side table | 1 |
| §3.2 `indexed=` declaration | 5 |
| §3.3 query surface (`where`, `order`, `offset`) | 7, 8 |
| §3.4 value normalization + `value_num` | 2 |
| §3.5 completeness manifest + fallback rule | 3, 7 |
| §3.6 explicit backfill | 9 |
| §3.7 index maintenance | 4, 5 |
| §3.8 introspection | 10 |
| §4 no migration | 11 |
| §6 slice 1 substrate / slice 2 log | 1–4, 6 / 5, 7–9 |
| §8 testing — parity, incomplete-never-lies, numeric, maintenance, additivity, batching | 7, 7, 8, 4, 11, 5 |

**Not in this plan, by design:** §3.3's `aggregate()` and `blob.find()`, and
routing `docs().where()` through the index — slices 3–6. Task 6 extracts the
shared compiler so slice 3 is a small change rather than a rewrite.

**Type consistency:** `FieldIndex(field, declared, complete, rows)` and
`QueryPlan(indexed, scanned, estimated_rows)` are defined in Task 10 and used
only there. `_INDEX_KIND = "log"` and `_item_key()` are introduced in Task 5 and
consumed unchanged in Tasks 7, 9 and 10. `plan_filters` returns a 4-tuple in
Task 7 and is unpacked as a 4-tuple in both Task 7 and Task 10.

**Known follow-up:** `AsyncLogBatch` indexes in a Python loop after its
`executemany` (Task 5). That is correct but gives back some of batching's
advantage. Measuring it, and folding index rows into the same `executemany`, is
worth an issue once there is a real workload to measure — AInBox's audit log
will be it.

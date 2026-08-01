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

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

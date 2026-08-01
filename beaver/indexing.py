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

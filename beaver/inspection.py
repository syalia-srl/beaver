"""Read-only, semantic inspection primitives for Beaver databases.

The inspector deliberately reads Beaver's physical tables instead of opening
managers. Discovery must work before a manager has been instantiated, encrypted
dictionaries must stay redacted, and browsing a queue must never consume it.
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
from typing import Any, Literal, TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from .core import AsyncBeaverDB


StoreKind = Literal[
    "dict",
    "list",
    "queue",
    "log",
    "docs",
    "vectors",
    "graph",
    "blob",
    "channel",
    "sketch",
    "lock",
]


class DatabaseInfo(BaseModel):
    path: str
    size_bytes: int
    wal_size_bytes: int
    beaver_version: str
    schema_version: int
    journal_mode: str
    read_only: bool
    data_version: int
    warnings: list[str]


class CatalogEntry(BaseModel):
    kind: StoreKind
    name: str
    count: int | None
    count_is_exact: bool
    browsable: bool
    internal: bool
    warnings: list[str]


class Page(BaseModel):
    items: list[dict[str, Any]]
    next_cursor: str | None
    has_more: bool
    total: int | None
    total_is_exact: bool
    warnings: list[str]


class FieldIndexInfo(BaseModel):
    field: str
    declared: bool
    complete: bool
    rows: int


class IndexSummary(BaseModel):
    kind: StoreKind
    name: str
    items: int
    fts_items: int | None
    fuzzy_items: int | None
    field_indexes: list[FieldIndexInfo]
    warnings: list[str]


class _StoreSpec(BaseModel):
    kind: StoreKind
    table: str
    name_column: str
    browsable: bool = False


_STORE_SPECS = (
    _StoreSpec(
        kind="dict", table="__beaver_dicts__", name_column="dict_name", browsable=True
    ),
    _StoreSpec(
        kind="list", table="__beaver_lists__", name_column="list_name", browsable=True
    ),
    _StoreSpec(
        kind="queue",
        table="__beaver_priority_queues__",
        name_column="queue_name",
        browsable=True,
    ),
    _StoreSpec(
        kind="log", table="__beaver_logs__", name_column="log_name", browsable=True
    ),
    _StoreSpec(
        kind="docs",
        table="__beaver_documents__",
        name_column="collection",
        browsable=True,
    ),
    _StoreSpec(
        kind="vectors",
        table="__beaver_vectors__",
        name_column="collection",
        browsable=True,
    ),
    _StoreSpec(
        kind="graph",
        table="__beaver_edges__",
        name_column="collection",
        browsable=True,
    ),
    _StoreSpec(
        kind="blob",
        table="__beaver_blobs__",
        name_column="store_name",
        browsable=True,
    ),
    _StoreSpec(
        kind="channel",
        table="__beaver_pubsub_log__",
        name_column="channel_name",
        browsable=True,
    ),
    _StoreSpec(
        kind="sketch",
        table="__beaver_sketches__",
        name_column="name",
        browsable=True,
    ),
    _StoreSpec(
        kind="lock",
        table="__beaver_lock_waiters__",
        name_column="lock_name",
        browsable=True,
    ),
)
_BROWSABLE_KINDS = frozenset(
    {
        "dict",
        "list",
        "queue",
        "log",
        "docs",
        "vectors",
        "graph",
        "blob",
        "channel",
        "sketch",
        "lock",
    }
)
_MAX_PAGE_SIZE = 50
_MAX_VALUE_BYTES = 64 * 1024
_VALUE_PREVIEW_CHARS = 2_048
_MAX_SEARCH_CHARS = 256
_MAX_VECTOR_COMPONENTS = 4_096
_MAX_BLOB_PREVIEW_BYTES = 64 * 1024
_MAX_JSON_DEPTH = 32


def _is_internal(kind: str, name: str) -> bool:
    if kind == "dict":
        return name in {"__metadata__", "__security__", "__beaver_event_registry__"}
    if kind == "channel":
        return name.startswith("__events_")
    if kind == "lock":
        return name.startswith(("__lock__", "__internal_lock__"))
    return False


def _encode_cursor(kind: str, **values: Any) -> str:
    raw = json.dumps({"kind": kind, **values}, separators=(",", ":"), sort_keys=True)
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str | None, kind: str) -> dict[str, Any] | None:
    if cursor is None:
        return None
    try:
        padding = "=" * (-len(cursor) % 4)
        value = json.loads(
            base64.b64decode(cursor + padding, altchars=b"-_", validate=True)
        )
        if not isinstance(value, dict) or value.pop("kind", None) != kind:
            raise ValueError
        return value
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid or mismatched page cursor.") from exc


def _too_deep(value: Any) -> bool:
    stack = [(value, 1)]
    while stack:
        current, depth = stack.pop()
        if depth > _MAX_JSON_DEPTH:
            return True
        if isinstance(current, dict):
            stack.extend((child, depth + 1) for child in current.values())
        elif isinstance(current, list):
            stack.extend((child, depth + 1) for child in current)
    return False


def _decode_json(raw: str | bytes, field: str) -> dict[str, Any]:
    if isinstance(raw, bytes):
        return {
            f"{field}_preview_base64": base64.b64encode(
                raw[:_VALUE_PREVIEW_CHARS]
            ).decode("ascii"),
            f"{field}_size_bytes": len(raw),
            "truncated": len(raw) > _VALUE_PREVIEW_CHARS,
            "warnings": [
                f"Stored {field} is binary rather than JSON text; showing base64."
            ],
        }
    size = len(raw.encode("utf-8", errors="replace"))
    if size > _MAX_VALUE_BYTES:
        return {
            f"{field}_preview": raw[:_VALUE_PREVIEW_CHARS],
            f"{field}_size_bytes": size,
            "truncated": True,
            "warnings": [
                f"Stored {field} exceeds {_MAX_VALUE_BYTES} bytes and was truncated."
            ],
        }
    try:
        value = json.loads(raw)
        if _too_deep(value):
            return {
                f"{field}_preview": raw[:_VALUE_PREVIEW_CHARS],
                f"{field}_size_bytes": size,
                "truncated": True,
                "warnings": [
                    f"Stored {field} exceeds the maximum JSON depth of {_MAX_JSON_DEPTH}."
                ],
            }
        return {field: value, "warnings": []}
    except (json.JSONDecodeError, RecursionError, TypeError):
        return {
            f"raw_{field}": raw,
            "warnings": [
                "Stored value is not valid JSON; showing its raw representation."
            ],
        }


def _decode_optional_json(raw: str | bytes | None, field: str) -> dict[str, Any]:
    if raw is None:
        return {field: None, "warnings": []}
    return _decode_json(raw, field)


def _fts_query(value: str) -> str:
    tokens = re.findall(r"\w+", value, flags=re.UNICODE)
    if not tokens:
        raise ValueError("Document search must contain at least one word or number.")
    return " ".join(f'"{token}"' for token in tokens)


def _first_column(row: Any | None) -> Any:
    if row is None:
        raise RuntimeError("Expected the SQLite query to return one row.")
    return row[0]


class AsyncBeaverInspector:
    """Inspect a connected Beaver database without invoking manager mutations."""

    def __init__(self, db: "AsyncBeaverDB"):
        self._db = db

    async def info(self) -> DatabaseInfo:
        from . import __version__

        schema = await self._db.connection.execute("PRAGMA user_version")
        journal = await self._db.connection.execute("PRAGMA journal_mode")
        data_version = await self._db.connection.execute("PRAGMA data_version")
        path = getattr(self._db, "path", self._db._db_path)
        on_disk = path != ":memory:"
        warnings = []
        if not getattr(self._db, "read_only", False):
            warnings.append(
                "Database connection is writable; Studio should use read-only mode."
            )
        return DatabaseInfo(
            path=path,
            size_bytes=os.path.getsize(path) if on_disk and os.path.exists(path) else 0,
            wal_size_bytes=(
                os.path.getsize(f"{path}-wal")
                if on_disk and os.path.exists(f"{path}-wal")
                else 0
            ),
            beaver_version=__version__,
            schema_version=_first_column(await schema.fetchone()),
            journal_mode=_first_column(await journal.fetchone()),
            read_only=getattr(self._db, "read_only", False),
            data_version=_first_column(await data_version.fetchone()),
            warnings=warnings,
        )

    async def catalog(self, *, include_internal: bool = False) -> list[CatalogEntry]:
        entries: list[CatalogEntry] = []
        now = time.time()
        for spec in _STORE_SPECS:
            cursor = await self._db.connection.execute(
                f"SELECT {spec.name_column}, COUNT(*) FROM {spec.table} "
                f"GROUP BY {spec.name_column} ORDER BY {spec.name_column}"
            )
            for name, physical_count in await cursor.fetchall():
                internal = _is_internal(spec.kind, name)
                if internal and not include_internal:
                    continue
                warnings: list[str] = []
                count: int | None = physical_count
                exact = True
                if spec.kind == "sketch":
                    count = None
                    exact = False
                    warnings.append(
                        "Open the sketch viewer for approximate cardinality."
                    )
                elif spec.kind == "dict":
                    expired_cursor = await self._db.connection.execute(
                        "SELECT COUNT(*) FROM __beaver_dicts__ "
                        "WHERE dict_name = ? AND expires_at IS NOT NULL AND expires_at <= ?",
                        (name, now),
                    )
                    expired = _first_column(await expired_cursor.fetchone())
                    if expired:
                        warnings.append(
                            f"{expired} expired row(s) remain physically stored and are included in count."
                        )
                if not spec.browsable:
                    warnings.append(
                        "A modality-specific viewer is planned after the MVP."
                    )
                entries.append(
                    CatalogEntry(
                        kind=spec.kind,
                        name=name,
                        count=count,
                        count_is_exact=exact,
                        browsable=spec.browsable,
                        internal=internal,
                        warnings=warnings,
                    )
                )
        return sorted(entries, key=lambda entry: (entry.kind, entry.name))

    async def page(
        self,
        kind: str,
        name: str,
        *,
        limit: int = 50,
        cursor: str | None = None,
        query: str | None = None,
        search: str | None = None,
        start: float | None = None,
        end: float | None = None,
        source: str | None = None,
        target: str | None = None,
        label: str | None = None,
    ) -> Page:
        if kind not in _BROWSABLE_KINDS:
            raise ValueError(f"Unsupported or not-yet-browsable store kind: {kind!r}.")
        if not 1 <= limit <= _MAX_PAGE_SIZE:
            raise ValueError(f"limit must be between 1 and {_MAX_PAGE_SIZE}.")
        if query is not None and len(query) > _MAX_SEARCH_CHARS:
            raise ValueError(
                f"Document search must be at most {_MAX_SEARCH_CHARS} characters."
            )
        if start is not None and end is not None and start > end:
            raise ValueError("start must be less than or equal to end.")
        position = _decode_cursor(cursor, kind)
        if kind == "docs":
            if any(value is not None for value in (start, end, source, target, label)):
                raise ValueError("Document pages do not accept range or graph filters.")
            return await self._page_docs(
                name, limit, position, query=query, search=search
            )
        if query is not None or search is not None:
            raise ValueError("Search parameters are only supported for documents.")
        if kind in {"log", "channel"}:
            if any(value is not None for value in (source, target, label)):
                raise ValueError("Graph filters are only supported for graphs.")
        if kind == "log":
            return await self._page_log(name, limit, position, start=start, end=end)
        if kind == "channel":
            return await self._page_channel(name, limit, position, start=start, end=end)
        if kind == "graph":
            if start is not None or end is not None:
                raise ValueError(
                    "Time ranges are only supported for logs and channels."
                )
            return await self._page_graph(
                name,
                limit,
                position,
                source=source,
                target=target,
                label=label,
            )
        if any(value is not None for value in (start, end, source, target, label)):
            raise ValueError("This store kind does not support the requested filters.")
        method = getattr(self, f"_page_{kind}")
        return await method(name, limit, position)

    async def _page_dict(
        self, name: str, limit: int, position: dict[str, Any] | None
    ) -> Page:
        encrypted_cursor = await self._db.connection.execute(
            "SELECT 1 FROM __beaver_dicts__ WHERE dict_name = '__security__' AND key = ?",
            (name,),
        )
        encrypted = await encrypted_cursor.fetchone() is not None
        params: list[Any] = [name]
        where = "dict_name = ?"
        if position is not None:
            try:
                params.append(position["key"])
            except KeyError as exc:
                raise ValueError("Invalid dict page cursor.") from exc
            where += " AND key > ?"
        params.append(limit + 1)
        rows = list(
            await (
                await self._db.connection.execute(
                    "SELECT key, value, expires_at FROM __beaver_dicts__ "
                    f"WHERE {where} ORDER BY key ASC LIMIT ?",
                    params,
                )
            ).fetchall()
        )
        visible = rows[:limit]
        items = []
        now = time.time()
        for row in visible:
            item: dict[str, Any] = {
                "kind": "dict",
                "key": row["key"],
                "expires_at": row["expires_at"],
                "expired": row["expires_at"] is not None and row["expires_at"] <= now,
                "redacted": encrypted,
                "warnings": [],
            }
            if encrypted:
                item["warnings"].append("Encrypted dictionary value is redacted.")
            else:
                item.update(_decode_json(row["value"], "value"))
            items.append(item)
        next_cursor = None
        has_more = len(rows) > limit
        if has_more:
            next_cursor = _encode_cursor("dict", key=visible[-1]["key"])
        total = await self._count("__beaver_dicts__", "dict_name", name)
        return Page(
            items=items,
            next_cursor=next_cursor,
            has_more=has_more,
            total=total,
            total_is_exact=True,
            warnings=[],
        )

    async def _page_list(
        self, name: str, limit: int, position: dict[str, Any] | None
    ) -> Page:
        params: list[Any] = [name]
        where = "list_name = ?"
        start_index = 0
        if position is not None:
            try:
                params.append(position["item_order"])
                start_index = int(position["index"]) + 1
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("Invalid list page cursor.") from exc
            where += " AND item_order > ?"
        params.append(limit + 1)
        rows = list(
            await (
                await self._db.connection.execute(
                    "SELECT item_order, item_value FROM __beaver_lists__ "
                    f"WHERE {where} ORDER BY item_order ASC LIMIT ?",
                    params,
                )
            ).fetchall()
        )
        visible = rows[:limit]
        items = []
        for index, row in enumerate(visible, start=start_index):
            item = {"kind": "list", "index": index}
            item.update(_decode_json(row["item_value"], "value"))
            items.append(item)
        next_cursor = None
        has_more = len(rows) > limit
        if has_more:
            next_cursor = _encode_cursor(
                "list",
                item_order=visible[-1]["item_order"],
                index=start_index + len(visible) - 1,
            )
        total = await self._count("__beaver_lists__", "list_name", name)
        return Page(
            items=items,
            next_cursor=next_cursor,
            has_more=has_more,
            total=total,
            total_is_exact=True,
            warnings=[],
        )

    async def _page_queue(
        self, name: str, limit: int, position: dict[str, Any] | None
    ) -> Page:
        params: list[Any] = [name]
        where = "queue_name = ?"
        if position is not None:
            try:
                params.extend(
                    [position["priority"], position["timestamp"], position["rowid"]]
                )
            except KeyError as exc:
                raise ValueError("Invalid queue page cursor.") from exc
            where += " AND (priority, timestamp, rowid) > (?, ?, ?)"
        params.append(limit + 1)
        rows = list(
            await (
                await self._db.connection.execute(
                    "SELECT rowid, priority, timestamp, data "
                    "FROM __beaver_priority_queues__ "
                    f"WHERE {where} ORDER BY priority, timestamp, rowid LIMIT ?",
                    params,
                )
            ).fetchall()
        )
        visible = rows[:limit]
        items = []
        for row in visible:
            item = {
                "kind": "queue",
                "rowid": row["rowid"],
                "priority": row["priority"],
                "timestamp": row["timestamp"],
            }
            item.update(_decode_json(row["data"], "data"))
            items.append(item)
        next_cursor = None
        has_more = len(rows) > limit
        if has_more:
            last = visible[-1]
            next_cursor = _encode_cursor(
                "queue",
                priority=last["priority"],
                timestamp=last["timestamp"],
                rowid=last["rowid"],
            )
        total = await self._count("__beaver_priority_queues__", "queue_name", name)
        return Page(
            items=items,
            next_cursor=next_cursor,
            has_more=has_more,
            total=total,
            total_is_exact=True,
            warnings=[],
        )

    async def _page_log(
        self,
        name: str,
        limit: int,
        position: dict[str, Any] | None,
        *,
        start: float | None,
        end: float | None,
    ) -> Page:
        params: list[Any] = [name]
        where = "log_name = ?"
        if position is not None:
            try:
                params.append(position["timestamp"])
            except KeyError as exc:
                raise ValueError("Invalid log page cursor.") from exc
            if position.get("start") != start or position.get("end") != end:
                raise ValueError("Log page cursor does not match the requested range.")
            where += " AND timestamp > ?"
        if start is not None:
            where += " AND timestamp >= ?"
            params.append(start)
        if end is not None:
            where += " AND timestamp <= ?"
            params.append(end)
        params.append(limit + 1)
        rows = list(
            await (
                await self._db.connection.execute(
                    "SELECT timestamp, data FROM __beaver_logs__ "
                    f"WHERE {where} ORDER BY timestamp ASC LIMIT ?",
                    params,
                )
            ).fetchall()
        )
        visible = rows[:limit]
        items = []
        for row in visible:
            item = {"kind": "log", "timestamp": row["timestamp"]}
            item.update(_decode_json(row["data"], "data"))
            items.append(item)
        has_more = len(rows) > limit
        next_cursor = None
        if visible:
            next_cursor = _encode_cursor(
                "log",
                timestamp=visible[-1]["timestamp"],
                start=start,
                end=end,
            )
        elif position is not None:
            next_cursor = _encode_cursor(
                "log", timestamp=position["timestamp"], start=start, end=end
            )
        count_params: list[Any] = [name]
        count_where = "log_name = ?"
        if start is not None:
            count_where += " AND timestamp >= ?"
            count_params.append(start)
        if end is not None:
            count_where += " AND timestamp <= ?"
            count_params.append(end)
        count_cursor = await self._db.connection.execute(
            f"SELECT COUNT(*) FROM __beaver_logs__ WHERE {count_where}",
            count_params,
        )
        total = _first_column(await count_cursor.fetchone())
        return Page(
            items=items,
            next_cursor=next_cursor,
            has_more=has_more,
            total=total,
            total_is_exact=True,
            warnings=[],
        )

    async def _page_docs(
        self,
        name: str,
        limit: int,
        position: dict[str, Any] | None,
        *,
        query: str | None,
        search: str | None,
    ) -> Page:
        mode = search or ("fts" if query else "none")
        if mode not in {"none", "fts", "fuzzy"}:
            raise ValueError("Document search must be one of: none, fts, fuzzy.")
        if mode == "none" and query:
            raise ValueError("A document query requires fts or fuzzy search.")
        if mode != "none" and not query:
            raise ValueError("Document search requires a non-empty query.")

        if position is not None:
            if position.get("query") != query or position.get("search") != mode:
                raise ValueError(
                    "Document page cursor does not match the requested search."
                )

        if mode == "none":
            params: list[Any] = [name]
            where = "collection = ?"
            if position is not None:
                try:
                    params.append(position["item_id"])
                except KeyError as exc:
                    raise ValueError("Invalid document page cursor.") from exc
                where += " AND item_id > ?"
            params.append(limit + 1)
            rows = list(
                await (
                    await self._db.connection.execute(
                        "SELECT item_id, data, NULL AS score "
                        "FROM __beaver_documents__ "
                        f"WHERE {where} ORDER BY item_id ASC LIMIT ?",
                        params,
                    )
                ).fetchall()
            )
            total: int | None = await self._count(
                "__beaver_documents__", "collection", name
            )
            total_is_exact = True
        else:
            offset = 0
            if position is not None:
                try:
                    offset = int(position["offset"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError("Invalid document search cursor.") from exc
            if mode == "fts":
                safe_query = _fts_query(query or "")
                rows = list(
                    await (
                        await self._db.connection.execute(
                            "SELECT d.item_id, d.data, MIN(f.rank) AS score "
                            "FROM __beaver_documents__ d "
                            "JOIN __beaver_fts_index__ f "
                            "ON d.collection = f.collection AND d.item_id = f.item_id "
                            "WHERE d.collection = ? AND __beaver_fts_index__ MATCH ? "
                            "GROUP BY d.item_id ORDER BY score ASC, d.item_id ASC "
                            "LIMIT ? OFFSET ?",
                            (name, safe_query, limit + 1, offset),
                        )
                    ).fetchall()
                )
            else:
                normalized = (query or "").lower()
                trigrams = sorted(
                    {
                        normalized[index : index + 3]
                        for index in range(max(0, len(normalized) - 2))
                    }
                )
                if not trigrams:
                    rows = []
                else:
                    placeholders = ",".join("?" for _ in trigrams)
                    rows = list(
                        await (
                            await self._db.connection.execute(
                                "SELECT d.item_id, d.data, matches.score AS score "
                                "FROM __beaver_documents__ d "
                                "JOIN (SELECT item_id, COUNT(*) AS score "
                                "FROM __beaver_trigrams__ "
                                f"WHERE collection = ? AND trigram IN ({placeholders}) "
                                "GROUP BY item_id) matches ON d.item_id = matches.item_id "
                                "WHERE d.collection = ? "
                                "ORDER BY score DESC, d.item_id ASC LIMIT ? OFFSET ?",
                                (name, *trigrams, name, limit + 1, offset),
                            )
                        ).fetchall()
                    )
            total = None
            total_is_exact = False

        visible = rows[:limit]
        items = []
        for row in visible:
            item: dict[str, Any] = {"kind": "docs", "id": row["item_id"]}
            item.update(_decode_json(row["data"], "body"))
            if mode != "none":
                item["score"] = row["score"]
            items.append(item)

        has_more = len(rows) > limit
        next_cursor = None
        if has_more:
            if mode == "none":
                next_cursor = _encode_cursor(
                    "docs",
                    item_id=visible[-1]["item_id"],
                    query=query,
                    search=mode,
                )
            else:
                next_cursor = _encode_cursor(
                    "docs",
                    offset=(position.get("offset", 0) if position else 0)
                    + len(visible),
                    query=query,
                    search=mode,
                )
        return Page(
            items=items,
            next_cursor=next_cursor,
            has_more=has_more,
            total=total,
            total_is_exact=total_is_exact,
            warnings=[],
        )

    async def _page_vectors(
        self, name: str, limit: int, position: dict[str, Any] | None
    ) -> Page:
        import numpy as np

        params: list[Any] = [name]
        where = "v.collection = ?"
        if position is not None:
            try:
                params.append(position["item_id"])
            except KeyError as exc:
                raise ValueError("Invalid vector page cursor.") from exc
            where += " AND v.item_id > ?"
        params.append(limit + 1)
        rows = list(
            await (
                await self._db.connection.execute(
                    "SELECT v.item_id, v.vector, v.metadata, "
                    "EXISTS(SELECT 1 FROM __beaver_lsh_index__ i "
                    "WHERE i.collection = v.collection AND i.item_id = v.item_id) "
                    "AS lsh_indexed FROM __beaver_vectors__ v "
                    f"WHERE {where} ORDER BY v.item_id ASC LIMIT ?",
                    params,
                )
            ).fetchall()
        )
        visible = rows[:limit]
        items = []
        for row in visible:
            warnings: list[str] = []
            raw = row["vector"]
            dimension = len(raw) // 4
            norm: float | None = None
            if len(raw) % 4:
                warnings.append("Vector byte length is not valid float32 data.")
            else:
                norm = float(np.linalg.norm(np.frombuffer(raw, dtype=np.float32)))
            metadata = _decode_optional_json(row["metadata"], "metadata")
            warnings.extend(metadata.pop("warnings"))
            items.append(
                {
                    "kind": "vectors",
                    "id": row["item_id"],
                    "dimension": dimension,
                    "norm": norm,
                    "lsh_indexed": bool(row["lsh_indexed"]),
                    **metadata,
                    "warnings": warnings,
                }
            )
        has_more = len(rows) > limit
        next_cursor = (
            _encode_cursor("vectors", item_id=visible[-1]["item_id"])
            if has_more
            else None
        )
        return Page(
            items=items,
            next_cursor=next_cursor,
            has_more=has_more,
            total=await self._count("__beaver_vectors__", "collection", name),
            total_is_exact=True,
            warnings=[],
        )

    async def _page_blob(
        self, name: str, limit: int, position: dict[str, Any] | None
    ) -> Page:
        params: list[Any] = [name]
        where = "store_name = ?"
        if position is not None:
            try:
                params.append(position["key"])
            except KeyError as exc:
                raise ValueError("Invalid blob page cursor.") from exc
            where += " AND key > ?"
        params.append(limit + 1)
        rows = list(
            await (
                await self._db.connection.execute(
                    "SELECT key, length(data) AS size_bytes, metadata "
                    f"FROM __beaver_blobs__ WHERE {where} "
                    "ORDER BY key ASC LIMIT ?",
                    params,
                )
            ).fetchall()
        )
        visible = rows[:limit]
        items = []
        for row in visible:
            item = {
                "kind": "blob",
                "key": row["key"],
                "size_bytes": row["size_bytes"],
            }
            item.update(_decode_optional_json(row["metadata"], "metadata"))
            items.append(item)
        has_more = len(rows) > limit
        next_cursor = (
            _encode_cursor("blob", key=visible[-1]["key"]) if has_more else None
        )
        return Page(
            items=items,
            next_cursor=next_cursor,
            has_more=has_more,
            total=await self._count("__beaver_blobs__", "store_name", name),
            total_is_exact=True,
            warnings=[],
        )

    async def _page_graph(
        self,
        name: str,
        limit: int,
        position: dict[str, Any] | None,
        *,
        source: str | None,
        target: str | None,
        label: str | None,
    ) -> Page:
        filters = {"source": source, "target": target, "label": label}
        if position is not None and position.get("filters") != filters:
            raise ValueError("Graph page cursor does not match the requested filters.")
        params: list[Any] = [name]
        where = "collection = ?"
        for column, value in (
            ("source_item_id", source),
            ("target_item_id", target),
            ("label", label),
        ):
            if value is not None:
                where += f" AND {column} = ?"
                params.append(value)
        if position is not None:
            try:
                params.extend(
                    [position["source"], position["target"], position["label"]]
                )
            except KeyError as exc:
                raise ValueError("Invalid graph page cursor.") from exc
            where += " AND (source_item_id, target_item_id, label) > (?, ?, ?)"
        count_params = list(params)
        if position is not None:
            count_params = count_params[:-3]
        params.append(limit + 1)
        rows = list(
            await (
                await self._db.connection.execute(
                    "SELECT source_item_id, target_item_id, label, metadata "
                    f"FROM __beaver_edges__ WHERE {where} "
                    "ORDER BY source_item_id, target_item_id, label LIMIT ?",
                    params,
                )
            ).fetchall()
        )
        visible = rows[:limit]
        items = []
        for row in visible:
            item = {
                "kind": "graph",
                "source": row["source_item_id"],
                "target": row["target_item_id"],
                "label": row["label"],
            }
            item.update(_decode_optional_json(row["metadata"], "metadata"))
            items.append(item)
        has_more = len(rows) > limit
        next_cursor = None
        if has_more:
            last = visible[-1]
            next_cursor = _encode_cursor(
                "graph",
                source=last["source_item_id"],
                target=last["target_item_id"],
                label=last["label"],
                filters=filters,
            )
        count_where = "collection = ?"
        for column, value in (
            ("source_item_id", source),
            ("target_item_id", target),
            ("label", label),
        ):
            if value is not None:
                count_where += f" AND {column} = ?"
        count_cursor = await self._db.connection.execute(
            f"SELECT COUNT(*) FROM __beaver_edges__ WHERE {count_where}",
            count_params,
        )
        return Page(
            items=items,
            next_cursor=next_cursor,
            has_more=has_more,
            total=_first_column(await count_cursor.fetchone()),
            total_is_exact=True,
            warnings=[],
        )

    async def _page_channel(
        self,
        name: str,
        limit: int,
        position: dict[str, Any] | None,
        *,
        start: float | None,
        end: float | None,
    ) -> Page:
        params: list[Any] = [name]
        where = "channel_name = ?"
        if position is not None:
            try:
                params.append(position["timestamp"])
            except KeyError as exc:
                raise ValueError("Invalid channel page cursor.") from exc
            if position.get("start") != start or position.get("end") != end:
                raise ValueError("Channel cursor does not match the requested range.")
            where += " AND timestamp > ?"
        if start is not None:
            where += " AND timestamp >= ?"
            params.append(start)
        if end is not None:
            where += " AND timestamp <= ?"
            params.append(end)
        params.append(limit + 1)
        rows = list(
            await (
                await self._db.connection.execute(
                    "SELECT timestamp, message_payload FROM __beaver_pubsub_log__ "
                    f"WHERE {where} ORDER BY timestamp ASC LIMIT ?",
                    params,
                )
            ).fetchall()
        )
        visible = rows[:limit]
        items = []
        for row in visible:
            item = {"kind": "channel", "timestamp": row["timestamp"]}
            item.update(_decode_json(row["message_payload"], "payload"))
            items.append(item)
        has_more = len(rows) > limit
        next_cursor = None
        if has_more:
            next_cursor = _encode_cursor(
                "channel",
                timestamp=visible[-1]["timestamp"],
                start=start,
                end=end,
            )
        count_params: list[Any] = [name]
        count_where = "channel_name = ?"
        if start is not None:
            count_where += " AND timestamp >= ?"
            count_params.append(start)
        if end is not None:
            count_where += " AND timestamp <= ?"
            count_params.append(end)
        count_cursor = await self._db.connection.execute(
            f"SELECT COUNT(*) FROM __beaver_pubsub_log__ WHERE {count_where}",
            count_params,
        )
        return Page(
            items=items,
            next_cursor=next_cursor,
            has_more=has_more,
            total=_first_column(await count_cursor.fetchone()),
            total_is_exact=True,
            warnings=[],
        )

    async def _page_sketch(
        self, name: str, limit: int, position: dict[str, Any] | None
    ) -> Page:
        if position is not None:
            raise ValueError("Sketch summaries do not use page cursors.")
        cursor = await self._db.connection.execute(
            "SELECT type, capacity, error_rate, data FROM __beaver_sketches__ "
            "WHERE name = ?",
            (name,),
        )
        row = await cursor.fetchone()
        items = []
        warnings = []
        if row is not None:
            approximate_count: int | None = None
            try:
                from .sketches import ApproximateSet

                approximate_count = len(
                    ApproximateSet(row["capacity"], row["error_rate"], row["data"])
                )
            except ValueError as exc:
                warnings.append(str(exc))
            items.append(
                {
                    "kind": "sketch",
                    "name": name,
                    "type": row["type"],
                    "capacity": row["capacity"],
                    "error_rate": row["error_rate"],
                    "size_bytes": len(row["data"]),
                    "approximate_count": approximate_count,
                    "warnings": warnings,
                }
            )
        return Page(
            items=items,
            next_cursor=None,
            has_more=False,
            total=len(items),
            total_is_exact=True,
            warnings=warnings,
        )

    async def _page_lock(
        self, name: str, limit: int, position: dict[str, Any] | None
    ) -> Page:
        params: list[Any] = [name]
        where = "lock_name = ?"
        start_index = 0
        if position is not None:
            try:
                params.extend([position["requested_at"], position["rowid"]])
                start_index = int(position["index"]) + 1
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("Invalid lock page cursor.") from exc
            where += " AND (requested_at, rowid) > (?, ?)"
        params.append(limit + 1)
        rows = list(
            await (
                await self._db.connection.execute(
                    "SELECT rowid, waiter_id, requested_at, expires_at "
                    "FROM __beaver_lock_waiters__ "
                    f"WHERE {where} ORDER BY requested_at, rowid LIMIT ?",
                    params,
                )
            ).fetchall()
        )
        visible = rows[:limit]
        now = time.time()
        items = []
        for index, row in enumerate(visible, start=start_index):
            expired = row["expires_at"] <= now
            items.append(
                {
                    "kind": "lock",
                    "waiter_id": row["waiter_id"],
                    "queue_position": index,
                    "requested_at": row["requested_at"],
                    "expires_at": row["expires_at"],
                    "age_seconds": max(0.0, now - row["requested_at"]),
                    "ttl_seconds": row["expires_at"] - now,
                    "expired": expired,
                    "status": (
                        "expired"
                        if expired
                        else ("holder" if index == 0 else "waiting")
                    ),
                    "warnings": (
                        ["Expired waiter remains physically stored."] if expired else []
                    ),
                }
            )
        has_more = len(rows) > limit
        next_cursor = None
        if has_more:
            last = visible[-1]
            next_cursor = _encode_cursor(
                "lock",
                requested_at=last["requested_at"],
                rowid=last["rowid"],
                index=start_index + len(visible) - 1,
            )
        return Page(
            items=items,
            next_cursor=next_cursor,
            has_more=has_more,
            total=await self._count("__beaver_lock_waiters__", "lock_name", name),
            total_is_exact=True,
            warnings=[],
        )

    async def detail(
        self,
        kind: str,
        name: str,
        item_id: str,
        *,
        preview_bytes: int = 16 * 1024,
    ) -> dict[str, Any]:
        if kind == "vectors":
            return await self._vector_detail(name, item_id)
        if kind == "blob":
            return await self._blob_detail(name, item_id, preview_bytes=preview_bytes)
        raise ValueError("Explicit item details are supported for vectors and blobs.")

    async def _vector_detail(self, name: str, item_id: str) -> dict[str, Any]:
        import numpy as np

        cursor = await self._db.connection.execute(
            "SELECT vector, metadata FROM __beaver_vectors__ "
            "WHERE collection = ? AND item_id = ?",
            (name, item_id),
        )
        row = await cursor.fetchone()
        if row is None:
            raise KeyError(item_id)
        raw = row["vector"]
        if len(raw) % 4:
            return {
                "kind": "vectors",
                "id": item_id,
                "vector": [],
                "dimension": len(raw) // 4,
                "truncated": True,
                "warnings": ["Vector byte length is not valid float32 data."],
            }
        vector = np.frombuffer(raw, dtype=np.float32)
        visible = vector[:_MAX_VECTOR_COMPONENTS].tolist()
        metadata = _decode_optional_json(row["metadata"], "metadata")
        warnings = metadata.pop("warnings")
        truncated = len(vector) > _MAX_VECTOR_COMPONENTS
        if truncated:
            warnings.append(
                f"Vector detail is limited to {_MAX_VECTOR_COMPONENTS} components."
            )
        return {
            "kind": "vectors",
            "id": item_id,
            "dimension": len(vector),
            "vector": visible,
            "truncated": truncated,
            **metadata,
            "warnings": warnings,
        }

    async def _blob_detail(
        self, name: str, key: str, *, preview_bytes: int
    ) -> dict[str, Any]:
        if not 1 <= preview_bytes <= _MAX_BLOB_PREVIEW_BYTES:
            raise ValueError(
                f"preview_bytes must be between 1 and {_MAX_BLOB_PREVIEW_BYTES}."
            )
        cursor = await self._db.connection.execute(
            "SELECT substr(data, 1, ?) AS preview, length(data) AS size_bytes, metadata "
            "FROM __beaver_blobs__ "
            "WHERE store_name = ? AND key = ?",
            (preview_bytes, name, key),
        )
        row = await cursor.fetchone()
        if row is None:
            raise KeyError(key)
        chunk: bytes = row["preview"]
        size_bytes: int = row["size_bytes"]
        metadata = _decode_optional_json(row["metadata"], "metadata")
        warnings = metadata.pop("warnings")
        metadata_value = metadata.get("metadata")
        content_type = (
            metadata_value.get("content_type")
            if isinstance(metadata_value, dict)
            else None
        )
        text_content = isinstance(content_type, str) and (
            content_type.startswith("text/")
            or content_type in {"application/json", "application/xml"}
        )
        if text_content:
            try:
                preview = chunk.decode("utf-8")
                encoding = "utf-8"
            except UnicodeDecodeError:
                preview = base64.b64encode(chunk).decode("ascii")
                encoding = "base64"
                warnings.append("Declared text payload is not valid UTF-8.")
        else:
            preview = base64.b64encode(chunk).decode("ascii")
            encoding = "base64"
        truncated = size_bytes > len(chunk)
        if truncated:
            warnings.append(
                f"Blob preview is limited to {preview_bytes} of {size_bytes} bytes."
            )
        return {
            "kind": "blob",
            "key": key,
            "size_bytes": size_bytes,
            "content_type": content_type,
            "preview": preview,
            "encoding": encoding,
            "truncated": truncated,
            **metadata,
            "warnings": warnings,
        }

    async def schema(self) -> list[dict[str, Any]]:
        cursor = await self._db.connection.execute(
            "SELECT name, type, sql FROM sqlite_master "
            "WHERE name NOT LIKE '__beaver_%' AND name NOT LIKE 'sqlite_%' "
            "AND type IN ('table', 'view') ORDER BY type, name"
        )
        objects = []
        for row in await cursor.fetchall():
            name = row["name"]
            quoted = '"' + name.replace('"', '""') + '"'
            columns_cursor = await self._db.connection.execute(
                f"PRAGMA table_info({quoted})"
            )
            columns = [
                {
                    "name": column["name"],
                    "type": column["type"],
                    "nullable": not bool(column["notnull"]),
                    "primary_key": bool(column["pk"]),
                }
                for column in await columns_cursor.fetchall()
            ]
            sql = row["sql"] or ""
            objects.append(
                {
                    "name": name,
                    "type": row["type"],
                    "columns": columns,
                    "sql": sql[:_VALUE_PREVIEW_CHARS],
                    "sql_truncated": len(sql) > _VALUE_PREVIEW_CHARS,
                }
            )
        return objects

    async def diagnostics(self) -> dict[str, Any]:
        from . import indexing

        field_indexes = await indexing.all_field_indexes(self._db.connection)
        fields = []
        for (kind, name), indexes in sorted(field_indexes.items()):
            for index in indexes:
                fields.append(
                    {
                        "kind": kind,
                        "name": name,
                        "field": index.field,
                        "complete": index.complete,
                        "rows": index.rows,
                    }
                )

        vector_cursor = await self._db.connection.execute(
            "SELECT v.collection, COUNT(DISTINCT v.item_id) AS items, "
            "COUNT(DISTINCT i.item_id) AS lsh_items, "
            "EXISTS(SELECT 1 FROM __beaver_lsh_config__ c "
            "WHERE c.collection = v.collection) AS configured "
            "FROM __beaver_vectors__ v LEFT JOIN __beaver_lsh_index__ i "
            "ON i.collection = v.collection AND i.item_id = v.item_id "
            "GROUP BY v.collection ORDER BY v.collection"
        )
        vectors = [
            {
                "name": row["collection"],
                "items": row["items"],
                "lsh_items": row["lsh_items"],
                "configured": bool(row["configured"]),
                "complete": row["items"] == row["lsh_items"],
            }
            for row in await vector_cursor.fetchall()
        ]

        document_cursor = await self._db.connection.execute(
            "SELECT DISTINCT collection FROM __beaver_documents__ ORDER BY collection"
        )
        documents = [
            (await self.indexes("docs", row["collection"])).model_dump()
            for row in await document_cursor.fetchall()
        ]
        return {
            "field_indexes": fields,
            "documents": documents,
            "vectors": vectors,
            "warnings": (
                [
                    "Incomplete indexes may be slower or less capable; Studio never repairs them in read-only mode."
                ]
                if any(not field["complete"] for field in fields)
                or any(not vector["complete"] for vector in vectors)
                else []
            ),
        }

    async def indexes(self, kind: str, name: str) -> IndexSummary:
        if kind != "docs":
            raise ValueError("Index summaries are currently supported for documents.")

        from . import indexing

        items = await self._count("__beaver_documents__", "collection", name)
        fts_cursor = await self._db.connection.execute(
            "SELECT COUNT(DISTINCT item_id) FROM __beaver_fts_index__ "
            "WHERE collection = ?",
            (name,),
        )
        fuzzy_cursor = await self._db.connection.execute(
            "SELECT COUNT(DISTINCT item_id) FROM __beaver_trigrams__ "
            "WHERE collection = ?",
            (name,),
        )
        fts_items = _first_column(await fts_cursor.fetchone())
        fuzzy_items = _first_column(await fuzzy_cursor.fetchone())
        fields = await indexing.field_indexes(self._db.connection, kind, name)
        warnings = []
        if fts_items < items:
            warnings.append(
                f"{items - fts_items} document(s) are not in the FTS index."
            )
        if fuzzy_items < items:
            warnings.append(
                f"{items - fuzzy_items} document(s) are not in the fuzzy index."
            )
        if any(not field.complete for field in fields):
            warnings.append("One or more declared field indexes are incomplete.")
        return IndexSummary(
            kind="docs",
            name=name,
            items=items,
            fts_items=fts_items,
            fuzzy_items=fuzzy_items,
            field_indexes=[
                FieldIndexInfo(
                    field=field.field,
                    declared=field.declared,
                    complete=field.complete,
                    rows=field.rows,
                )
                for field in fields
            ],
            warnings=warnings,
        )

    async def _count(self, table: str, name_column: str, name: str) -> int:
        cursor = await self._db.connection.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {name_column} = ?", (name,)
        )
        return _first_column(await cursor.fetchone())

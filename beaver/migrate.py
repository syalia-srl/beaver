"""Migrate a beaver 1.x database to the 2.x schema.

beaver 1.x named its tables with a single prefix (``beaver_dicts``,
``beaver_lists``, ...); 2.x uses dunder names (``__beaver_dicts__``, ...).
2.x refuses to open a 1.x file (see :class:`~beaver.core.BeaverLegacySchemaError`
and issues/41). This module produces a migrated 2.x copy.

Two safety properties hold by construction:

* **The source is only ever opened read-only.** Nothing here can mutate the
  1.x database, not even by checkpointing its WAL. A failed migration leaves
  the original exactly as it was.
* **The destination is a separate file.** There is no in-place mode, so there
  is never a window where a half-migrated database is the only copy.

See docs/migration-1x-to-2x.md.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass, field

from ._fracdex import key_between
from .core import LEGACY_1X_TABLES, AsyncBeaverDB, BeaverLegacySchemaError


#: 1.x tables whose schema is byte-identical to their 2.x counterpart.
STRAIGHT_COPY: dict[str, tuple[str, tuple[str, ...]]] = {
    "beaver_blobs": ("__beaver_blobs__", ("store_name", "key", "data", "metadata")),
    "beaver_logs": ("__beaver_logs__", ("log_name", "timestamp", "data")),
    "beaver_priority_queues": (
        "__beaver_priority_queues__",
        ("queue_name", "priority", "timestamp", "data"),
    ),
    "beaver_sketches": (
        "__beaver_sketches__",
        ("name", "type", "capacity", "error_rate", "data"),
    ),
    "beaver_edges": (
        "__beaver_edges__",
        ("collection", "source_item_id", "target_item_id", "label", "metadata"),
    ),
}

#: Derived indices. Copying them would carry a 1.x schema across, so they are
#: regenerated from the migrated data instead.
REBUILT: dict[str, str] = {
    "beaver_fts_index": "derived full-text index; regenerated from migrated documents",
    "beaver_trigrams": "derived fuzzy index, incompatible 1.x schema; regenerated",
}

#: Tables with no meaningful 2.x counterpart.
DROPPED: dict[str, str] = {
    "beaver_collection_versions": "cache-invalidation bookkeeping, meaningless across the version boundary",
    "beaver_manager_versions": "cache-invalidation bookkeeping, 2.x starts fresh at 0",
    "beaver_vector_change_log": "1.x incremental-index bookkeeping with no 2.x equivalent",
    "beaver_lock_waiters": "ephemeral runtime state from a process that is no longer running",
    "beaver_pubsub_log": "ephemeral undelivered pub/sub messages from a dead 1.x process",
}

_BATCH = 500


@dataclass
class MigrationReport:
    """What a migration did, or (dry run) what it would do."""

    source: str
    destination: str | None
    legacy_version: str
    dry_run: bool
    wal_bytes: int | None = None
    dicts: dict[str, int] = field(default_factory=dict)
    lists: dict[str, int] = field(default_factory=dict)
    documents: dict[str, int] = field(default_factory=dict)
    vectors: dict[str, int] = field(default_factory=dict)
    copied: dict[str, int] = field(default_factory=dict)
    rebuilt: dict[str, str] = field(default_factory=dict)
    dropped: dict[str, str] = field(default_factory=dict)
    #: Set on a dry run over a split-brain database. The migration itself is
    #: still refused; this only describes what is on each side.
    split_brain: bool = False
    #: kind -> {store name -> rows} for the 2.x half of a split-brain database.
    modern: dict[str, dict[str, int]] = field(default_factory=dict)

    @property
    def total_rows(self) -> int:
        return (
            sum(self.dicts.values())
            + sum(self.lists.values())
            + sum(self.documents.values())
            + sum(self.vectors.values())
            + sum(self.copied.values())
        )


def _open_readonly(path: str) -> sqlite3.Connection:
    """Open a database strictly read-only.

    A read-only connection cannot checkpoint, so merely inspecting the source
    leaves both the main file and its ``-wal`` sidecar byte-identical. SQLite
    still presents main+WAL as one coherent view, so uncommitted-to-main data
    in a hot WAL is read correctly rather than silently skipped.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def _table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def _count(conn: sqlite3.Connection, table: str) -> int:
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    except sqlite3.Error:
        return 0


def _legacy_version(conn: sqlite3.Connection) -> str:
    try:
        row = conn.execute(
            "SELECT value FROM beaver_dicts "
            "WHERE dict_name = '__metadata__' AND key = 'version'"
        ).fetchone()
    except sqlite3.Error:
        return "unknown"
    if row is None or row[0] is None:
        return "unknown"
    try:
        return str(json.loads(row[0]))
    except (TypeError, ValueError):
        return str(row[0])


def _wal_bytes(path: str) -> int | None:
    wal = path + "-wal"
    return os.path.getsize(wal) if os.path.exists(wal) else None


def _classify(conn: sqlite3.Connection, path: str) -> tuple[list[str], list[str]]:
    """Return (legacy tables, 2.x tables) present, rejecting non-1.x files."""
    names = _table_names(conn)
    legacy = sorted(names & LEGACY_1X_TABLES)
    if not legacy:
        raise BeaverLegacySchemaError(
            f"Database {path!r} has no beaver 1.x tables; there is nothing to "
            "migrate. If it is already a 2.x database, open it directly."
        )
    modern = sorted(n for n in names if n.startswith("__beaver_") and n.endswith("__"))
    return legacy, modern


def _require_migratable(conn: sqlite3.Connection, path: str) -> None:
    """Reject anything that is not a plain, untouched 1.x database."""
    legacy, modern = _classify(conn, path)
    if modern:
        raise BeaverLegacySchemaError(
            f"Database {path!r} is SPLIT-BRAIN: it holds both a beaver 1.x "
            "dataset and a beaver 2.x dataset side by side.\n"
            f"  legacy tables: {', '.join(legacy)}\n"
            f"  2.x tables: {', '.join(modern)}\n"
            "Automatic migration is refused. The two datasets are disjoint and "
            "reconciling them means deciding which writes win — an "
            "application-level judgement this tool must not make silently. "
            "Run `beaver migrate --dry-run` to see row counts on both sides, "
            "then dump and merge them deliberately. See "
            "docs/migration-1x-to-2x.md."
        )


#: Per-store 2.x tables, reported alongside their legacy counterparts so a
#: split-brain dry run can be read as a side-by-side comparison.
_MODERN_STORES: dict[str, tuple[str, str]] = {
    "dicts": ("__beaver_dicts__", "dict_name"),
    "lists": ("__beaver_lists__", "list_name"),
    "documents": ("__beaver_documents__", "collection"),
    "vectors": ("__beaver_vectors__", "collection"),
}


def _modern_side(
    conn: sqlite3.Connection, modern: list[str]
) -> dict[str, dict[str, int]]:
    """Row counts for the 2.x half of a split-brain database.

    Per-store for the four kinds that have a legacy counterpart, table-level
    for anything else that is non-empty.
    """
    present = set(modern)
    side: dict[str, dict[str, int]] = {}

    for kind, (table, column) in _MODERN_STORES.items():
        if table not in present:
            continue
        try:
            rows = conn.execute(
                f"SELECT {column}, COUNT(*) FROM {table} GROUP BY {column} ORDER BY {column}"
            ).fetchall()
        except sqlite3.Error:
            continue
        if rows:
            side[kind] = {name: n for name, n in rows}

    other = {}
    accounted = {table for table, _ in _MODERN_STORES.values()}
    for table in modern:
        if table in accounted:
            continue
        n = _count(conn, table)
        if n:
            other[table] = n
    if other:
        side["other tables"] = other

    return side


def plan_migration(source: str) -> MigrationReport:
    """Inspect a 1.x database read-only and report what a migration would do."""
    conn = _open_readonly(source)
    try:
        legacy, modern = _classify(conn, source)
        report = MigrationReport(
            source=source,
            destination=None,
            legacy_version=_legacy_version(conn),
            dry_run=True,
            wal_bytes=_wal_bytes(source),
            split_brain=bool(modern),
        )
        if modern:
            # Deliberately still described rather than refused: an operator who
            # hit the split-brain error needs counts on both sides to decide
            # which dataset matters. Migration itself remains refused.
            report.modern = _modern_side(conn, modern)
        names = _table_names(conn)

        for name, n in conn.execute(
            "SELECT dict_name, COUNT(*) FROM beaver_dicts "
            "WHERE dict_name != '__metadata__' GROUP BY dict_name ORDER BY dict_name"
        ):
            report.dicts[name] = n

        for name, n in conn.execute(
            "SELECT list_name, COUNT(*) FROM beaver_lists GROUP BY list_name ORDER BY list_name"
        ):
            report.lists[name] = n

        if "beaver_collections" in names:
            for name, docs, vecs in conn.execute(
                "SELECT collection, COUNT(metadata), COUNT(item_vector) "
                "FROM beaver_collections GROUP BY collection ORDER BY collection"
            ):
                if docs:
                    report.documents[name] = docs
                if vecs:
                    report.vectors[name] = vecs

        for legacy_table in STRAIGHT_COPY:
            if legacy_table in names:
                n = _count(conn, legacy_table)
                if n:
                    report.copied[legacy_table] = n

        for table, why in REBUILT.items():
            if table in names:
                report.rebuilt[table] = why
        for table, why in DROPPED.items():
            if table in names:
                n = _count(conn, table)
                report.dropped[table] = f"{why} ({n} rows)"

        return report
    finally:
        conn.close()


def _regenerate_order(count: int) -> list[str]:
    """Fractional-index keys for `count` items in ascending order.

    1.x stored ``item_order`` as a REAL midpoint value; 2.x uses a TEXT
    fractional index. The float values carry no meaning beyond their relative
    order, so they are discarded and fresh keys generated in sequence.
    """
    keys: list[str] = []
    prev: str | None = None
    for _ in range(count):
        prev = key_between(prev, None)
        keys.append(prev)
    return keys


async def migrate_database(source: str, destination: str) -> MigrationReport:
    """Write a 2.x copy of the 1.x database at `source` to `destination`.

    The source is opened read-only and never modified. `destination` must not
    already exist.
    """
    if os.path.exists(destination):
        raise FileExistsError(
            f"{destination!r} already exists; refusing to overwrite it."
        )

    src = _open_readonly(source)
    try:
        _require_migratable(src, source)
        report = MigrationReport(
            source=source,
            destination=destination,
            legacy_version=_legacy_version(src),
            dry_run=False,
            wal_bytes=_wal_bytes(source),
        )
        names = _table_names(src)

        db = AsyncBeaverDB(destination)
        await db.connect()
        try:
            out = db.connection
            async with db.transaction():
                await _copy_dicts(src, out, report)
                await _copy_lists(src, out, report)
                await _copy_straight(src, out, names, report)
                if "beaver_collections" in names:
                    await _copy_collections(src, out, names, report)

            for table, why in REBUILT.items():
                if table in names:
                    report.rebuilt[table] = why
            for table, why in DROPPED.items():
                if table in names:
                    report.dropped[table] = f"{why} ({_count(src, table)} rows)"
        finally:
            await db.close()

        return report
    finally:
        src.close()


async def _copy_dicts(src, out, report: MigrationReport) -> None:
    """Copy dict entries verbatim.

    Values are moved as opaque TEXT. beaver `Secret` fields are Fernet
    ciphertext in this column; never decoding it means the migrator needs no
    key material and encrypted values round-trip untouched.
    """
    cur = src.execute(
        "SELECT dict_name, key, value, expires_at FROM beaver_dicts "
        "WHERE dict_name != '__metadata__'"
    )
    while rows := cur.fetchmany(_BATCH):
        await out.executemany(
            "INSERT INTO __beaver_dicts__ (dict_name, key, value, expires_at) "
            "VALUES (?, ?, ?, ?)",
            rows,
        )
        for name, *_ in rows:
            report.dicts[name] = report.dicts.get(name, 0) + 1


async def _copy_lists(src, out, report: MigrationReport) -> None:
    """Copy lists, regenerating REAL orderings as TEXT fractional indices."""
    names = [
        row[0]
        for row in src.execute(
            "SELECT DISTINCT list_name FROM beaver_lists ORDER BY list_name"
        )
    ]
    for name in names:
        values = [
            row[0]
            for row in src.execute(
                "SELECT item_value FROM beaver_lists WHERE list_name = ? "
                "ORDER BY item_order",
                (name,),
            )
        ]
        keys = _regenerate_order(len(values))
        await out.executemany(
            "INSERT INTO __beaver_lists__ (list_name, item_order, item_value) "
            "VALUES (?, ?, ?)",
            [(name, k, v) for k, v in zip(keys, values)],
        )
        report.lists[name] = len(values)


async def _copy_straight(src, out, names: set[str], report: MigrationReport) -> None:
    for legacy_table, (modern_table, columns) in STRAIGHT_COPY.items():
        if legacy_table not in names:
            continue
        cols = ", ".join(columns)
        placeholders = ", ".join("?" * len(columns))
        cur = src.execute(f"SELECT {cols} FROM {legacy_table}")
        total = 0
        while rows := cur.fetchmany(_BATCH):
            await out.executemany(
                f"INSERT INTO {modern_table} ({cols}) VALUES ({placeholders})", rows
            )
            total += len(rows)
        if total:
            report.copied[legacy_table] = total


async def _copy_collections(src, out, names: set[str], report: MigrationReport) -> None:
    """Fan 1.x `beaver_collections` out into 2.x documents and vectors.

    1.x fused both into one table: `metadata` held the document JSON and
    `item_vector` the embedding. 2.x separates them into
    `__beaver_documents__` and `__beaver_vectors__`.
    """
    from .docs import _flatten_document

    fuzzy_collections: set[str] = set()
    if "beaver_trigrams" in names:
        fuzzy_collections = {
            row[0]
            for row in src.execute("SELECT DISTINCT collection FROM beaver_trigrams")
        }

    cur = src.execute(
        "SELECT collection, item_id, metadata, item_vector FROM beaver_collections"
    )
    while rows := cur.fetchmany(_BATCH):
        docs, fts, trigrams, vectors = [], [], [], []
        for collection, item_id, metadata, vector in rows:
            if metadata is not None:
                # Stored verbatim: the exact 1.x bytes, not a re-serialization.
                docs.append((collection, item_id, metadata))
                report.documents[collection] = report.documents.get(collection, 0) + 1
                try:
                    body = json.loads(metadata)
                except (TypeError, ValueError):
                    body = None
                if body is not None:
                    contents = [
                        (path, content)
                        for path, content in _flatten_document(body)
                        if content.strip()
                    ]
                    fts.extend(
                        (collection, item_id, path, content)
                        for path, content in contents
                    )
                    if collection in fuzzy_collections:
                        # Mirrors AsyncBeaverDocuments._index_trigrams exactly:
                        # all FTS field contents joined by a space, lowercased,
                        # then a sliding 3-char window over the whole string.
                        full_text = " ".join(content for _, content in contents)
                        trigrams.extend(
                            (collection, item_id, tri) for tri in _trigrams(full_text)
                        )
            if vector is not None:
                # Raw float32 buffer in both versions — copied byte-for-byte,
                # never reinterpreted.
                vectors.append((collection, item_id, vector, metadata))
                report.vectors[collection] = report.vectors.get(collection, 0) + 1

        if docs:
            await out.executemany(
                "INSERT OR REPLACE INTO __beaver_documents__ (collection, item_id, data) "
                "VALUES (?, ?, ?)",
                docs,
            )
        if fts:
            await out.executemany(
                "INSERT INTO __beaver_fts_index__ (collection, item_id, field_path, field_content) "
                "VALUES (?, ?, ?, ?)",
                fts,
            )
        if trigrams:
            await out.executemany(
                "INSERT OR IGNORE INTO __beaver_trigrams__ (collection, item_id, trigram) "
                "VALUES (?, ?, ?)",
                trigrams,
            )
        if vectors:
            await out.executemany(
                "INSERT OR REPLACE INTO __beaver_vectors__ (collection, item_id, vector, metadata) "
                "VALUES (?, ?, ?, ?)",
                vectors,
            )


def _trigrams(text: str) -> set[str]:
    """Same scheme as AsyncBeaverDocuments._index_trigrams."""
    clean = text.lower()
    if len(clean) < 3:
        return set()
    return {clean[i : i + 3] for i in range(len(clean) - 2)}


def format_report(report: MigrationReport) -> str:
    """Render a report for the terminal."""
    lines: list[str] = []
    verb = "would migrate" if report.dry_run else "migrated"
    lines.append(f"source:      {report.source}  (beaver {report.legacy_version})")
    lines.append(f"destination: {report.destination or '(dry run — nothing written)'}")
    if report.wal_bytes:
        lines.append(
            f"note:        a -wal sidecar of {report.wal_bytes} bytes is present and IS "
            "included in this read.\n"
            "             Any copy of this database must carry the -wal file with it."
        )
    lines.append("")

    def section(title: str, items: dict[str, int]) -> None:
        if not items:
            return
        lines.append(f"{title} ({len(items)}):")
        for name, n in sorted(items.items()):
            lines.append(f"  {name:<48} {n:>7} rows")
        lines.append("")

    if report.split_brain:
        lines.append("*** SPLIT-BRAIN — THIS DATABASE CANNOT BE MIGRATED ***")
        lines.append("")
        lines.append(
            "It holds a beaver 1.x dataset and a beaver 2.x dataset side by side.\n"
            "A 2.x process opened the 1.x file, read it as empty, and wrote its\n"
            "data into the 2.x tables. The two sides are disjoint: neither is a\n"
            "superset of the other, and no automatic merge is possible because\n"
            "deciding which writes win is an application-level judgement.\n"
            "\n"
            "Below is what each side holds, so you can make that decision. The\n"
            "real `beaver migrate` run refuses this database by design."
        )
        lines.append("")
        lines.append("--- 1.x side (the original data) ---")
        lines.append("")

    section("dicts", report.dicts)
    section(
        (
            "lists"
            if report.split_brain
            else "lists (ordering regenerated REAL -> fractional index)"
        ),
        report.lists,
    )
    section("collections -> documents", report.documents)
    section("collections -> vectors", report.vectors)
    section("copied verbatim", report.copied)

    if not report.split_brain:
        if report.rebuilt:
            lines.append(f"rebuilt ({len(report.rebuilt)}):")
            for name, why in sorted(report.rebuilt.items()):
                lines.append(f"  {name:<28} {why}")
            lines.append("")
        if report.dropped:
            lines.append(f"dropped ({len(report.dropped)}):")
            for name, why in sorted(report.dropped.items()):
                lines.append(f"  {name:<28} {why}")
            lines.append("")

        lines.append(f"total rows {verb}: {report.total_rows}")
        return "\n".join(lines)

    lines.append("--- 2.x side (written since that accidental open) ---")
    lines.append("")
    if not report.modern:
        lines.append("  (2.x tables exist but are all empty)")
        lines.append("")
    for kind, stores in report.modern.items():
        section(kind, stores)

    lines.append(
        f"1.x side: {report.total_rows} rows   |   "
        f"2.x side: {sum(sum(s.values()) for s in report.modern.values())} rows"
    )
    lines.append("")
    lines.append(
        "No migration path exists without a human decision. Take a copy of the\n"
        "file first, then dump each side and merge deliberately. Rolling back to\n"
        "beaver 1.x loses the 2.x side; continuing with 2.x leaves the 1.x side\n"
        "unreachable. See docs/migration-1x-to-2x.md."
    )
    return "\n".join(lines)

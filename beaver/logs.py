import asyncio
import json
import time
import sqlite3
from typing import (
    IO,
    Iterator,
    AsyncIterator,
    Protocol,
    runtime_checkable,
    NamedTuple,
)

from pydantic import BaseModel

from . import indexing
from .api import expose, local_only
from .manager import AsyncBeaverBase, atomic, emits
from .interfaces import LogEntry, IAsyncBeaverLog


class AsyncLogBatch[T: BaseModel]:
    """Async context manager for buffered bulk appends to a log.

    Buffers (timestamp, serialized_data) tuples on `log()`, flushing them in a
    single `executemany` on exit. Enforces strict timestamp monotonicity to
    avoid PK collisions in `__beaver_logs__` (the table's PK is (log_name, ts)).
    """

    def __init__(self, manager: "AsyncBeaverLog[T]"):
        self._manager = manager
        self._pending: list[tuple[str, float, str]] = []
        self._pending_items: list[tuple] = []
        self._last_ts: float = 0.0

    def log(self, data: T, timestamp: float | None = None) -> None:
        ts = timestamp if timestamp is not None else time.time()
        if ts <= self._last_ts:
            ts = self._last_ts + 1e-6
        self._last_ts = ts
        self._pending.append((self._manager._name, ts, self._manager._serialize(data)))
        # Keep the original object so the batch can index without re-parsing.
        self._pending_items.append((self._manager._name, ts, None, data))

    async def __aenter__(self) -> "AsyncLogBatch[T]":
        # Seed _last_ts from the table's current max so batched timestamps
        # don't collide with existing rows on the (log_name, timestamp) PK.
        cursor = await self._manager.connection.execute(
            "SELECT MAX(timestamp) FROM __beaver_logs__ WHERE log_name = ?",
            (self._manager._name,),
        )
        row = await cursor.fetchone()
        existing_max = row[0] if row and row[0] is not None else 0.0
        self._last_ts = max(existing_max, 0.0)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is not None or not self._pending:
            return
        async with self._manager._internal_lock:
            async with self._manager._db.transaction():
                await self._manager.connection.executemany(
                    "INSERT INTO __beaver_logs__ (log_name, timestamp, data) VALUES (?, ?, ?)",
                    self._pending,
                )
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
        self._pending.clear()
        self._pending_items.clear()


class AsyncBeaverLog[T: BaseModel](AsyncBeaverBase[T], IAsyncBeaverLog[T]):
    """
    A wrapper providing a Pythonic interface to a time-indexed log.
    Refactored for Async-First architecture (v2.0).
    """

    _INDEX_KIND = "log"

    @staticmethod
    def _item_key(ts: float) -> str:
        """repr() round-trips a float exactly; SQLite's CAST(x AS TEXT) does
        not always agree with it. Queries must compare CAST(item_key AS REAL)
        back to the timestamp, never text to text."""
        return repr(ts)

    async def _ensure_declared(self) -> None:
        """Record this log's `indexed=` declaration in the manifest.

        Declaration lands on the **first awaited operation**, not on `db.log()`:
        the factory is synchronous, so there is no await point at which to write
        the row. This is safe because an absent manifest row makes the planner
        fall back to a `json_extract` scan — slower, never wrong — while a
        `complete = 1` row, once written, persists in the database.
        """
        if self._indexed and not getattr(self, "_declared", False):
            await indexing.declare(
                self.connection, self._INDEX_KIND, self._name, self._indexed
            )
            self._declared = True

    @expose(
        path="/log",
        method="POST",
        cli_name="log",
        cli_help="Append an entry to the log.",
        body_param="data",
    )
    @emits("log", payload=lambda data, *args, **kwargs: dict(data=data))
    @atomic
    async def log(self, data: T, timestamp: float | None = None):
        """
        Appends an entry to the log.
        Ensures timestamp uniqueness (PK constraint) by micro-incrementing on collision.
        """
        ts = timestamp or time.time()
        serialized_data = self._serialize(data)

        # Retry loop to handle PK collisions (same microsecond)
        while True:
            try:
                await self.connection.execute(
                    "INSERT INTO __beaver_logs__ (log_name, timestamp, data) VALUES (?, ?, ?)",
                    (self._name, ts, serialized_data),
                )
                break
            except sqlite3.IntegrityError:
                # Collision detected: shift by 1 microsecond and retry
                ts += 0.000001

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

    @expose(
        path="/range",
        method="GET",
        cli_name="range",
        cli_help="List entries within a time range.",
    )
    async def range(
        self,
        start: float | None = None,
        end: float | None = None,
        limit: int | None = None,
        where: list | None = None,
        order: str = "ASC",
        offset: int | None = None,
    ) -> list[LogEntry[T]]:
        """
        Retrieves a list of log entries within a time range.
        """
        await self._ensure_declared()

        query = "SELECT timestamp, data FROM __beaver_logs__ AS l WHERE log_name = ?"
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

        direction = order.upper()
        if direction not in ("ASC", "DESC"):
            raise ValueError(f"order must be 'ASC' or 'DESC', got {order!r}")
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

        cursor = await self.connection.execute(query, tuple(params))
        rows = await cursor.fetchall()

        return [
            LogEntry(timestamp=row["timestamp"], data=self._deserialize(row["data"]))
            for row in rows
        ]

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
        await indexing.declare(self.connection, self._INDEX_KIND, self._name, target)
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

    @local_only(
        "log.live() is only available on local databases (infinite stream, no SSE yet)"
    )
    async def live(self, poll_interval: float = 0.1) -> AsyncIterator[LogEntry[T]]:
        """
        Yields new log entries as they are added in real-time.
        This is an infinite async generator.
        """
        # Start trailing from "now"
        last_ts = time.time()

        while True:
            # Poll for new items since last_ts
            cursor = await self.connection.execute(
                """
                SELECT timestamp, data FROM __beaver_logs__
                WHERE log_name = ? AND timestamp > ?
                ORDER BY timestamp ASC
                """,
                (self._name, last_ts),
            )
            rows = await cursor.fetchall()

            if rows:
                last_ts = rows[-1]["timestamp"]
                for row in rows:
                    yield LogEntry(
                        timestamp=row["timestamp"], data=self._deserialize(row["data"])
                    )

            # Non-blocking sleep yields control to the event loop
            await asyncio.sleep(poll_interval)

    @expose(
        path="/count",
        method="GET",
        cli_name="count",
        cli_help="Return the number of entries.",
    )
    async def count(self) -> int:
        """Returns the total number of entries in the log."""
        cursor = await self.connection.execute(
            "SELECT COUNT(*) FROM __beaver_logs__ WHERE log_name = ?", (self._name,)
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    @expose(
        path="/clear", method="POST", cli_name="clear", cli_help="Clear all entries."
    )
    @emits("clear", payload=lambda *args, **kwargs: dict())
    @atomic
    async def clear(self):
        """Clears all entries in this log."""
        await self.connection.execute(
            "DELETE FROM __beaver_logs__ WHERE log_name = ?", (self._name,)
        )
        await indexing.clear_index(self.connection, self._INDEX_KIND, self._name)

    async def _iter_dump_items(self):
        entries = await self.range()
        for entry in entries:
            val = entry.data
            if self._model and isinstance(val, BaseModel):
                val = json.loads(val.model_dump_json())
            yield {"timestamp": entry.timestamp, "data": val}

    @local_only(
        "log.dump() is only available on local databases (no chunked transfer yet)"
    )
    async def dump(
        self,
        fp: IO[str] | None = None,
        format: str = "json",
        indent: int = 2,
    ) -> dict | None:
        if format == "json":
            items_list = [item async for item in self._iter_dump_items()]
            dump_obj = {
                "metadata": {
                    "type": "Log",
                    "name": self._name,
                    "count": len(items_list),
                },
                "items": items_list,
            }
            if fp:
                json.dump(dump_obj, fp, indent=indent)
                return None
            return dump_obj
        if format == "jsonl":
            if fp is None:
                raise ValueError("JSONL format requires fp.")
            async for item in self._iter_dump_items():
                fp.write(json.dumps(item) + "\n")
            return None
        raise ValueError(f"Unsupported format: {format!r}. Use 'json' or 'jsonl'.")

    @local_only(
        "log.load() is only available on local databases (no chunked transfer yet)"
    )
    async def load(
        self,
        fp: IO[str],
        format: str = "json",
        strategy: str = "overwrite",
    ) -> None:
        """Loads log entries from a serialized dump (JSON or JSONL)."""
        if format not in ("json", "jsonl"):
            raise ValueError(f"Unsupported format: {format!r}. Use 'json' or 'jsonl'.")
        if strategy not in ("overwrite", "append"):
            raise ValueError(
                f"Unsupported strategy: {strategy!r}. Use 'overwrite' or 'append'."
            )

        if strategy == "overwrite":
            await self.clear()

        if format == "json":
            data = json.load(fp)
            for item in data.get("items", []):
                await self._load_item(item)
        else:  # jsonl
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                await self._load_item(json.loads(line))

    async def _load_item(self, item: dict) -> None:
        await self.log(item["data"], timestamp=item.get("timestamp"))

    @local_only(
        "log.batched() is only available on local databases (transactional session cannot cross HTTP)"
    )
    def batched(self) -> AsyncLogBatch[T]:
        """Returns an async context manager for buffered bulk appends."""
        return AsyncLogBatch(self)

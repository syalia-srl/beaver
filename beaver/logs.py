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

from .manager import AsyncBeaverBase, atomic, emits
from .interfaces import LogEntry, IAsyncBeaverLog


class AsyncBeaverLog[T: BaseModel](AsyncBeaverBase[T], IAsyncBeaverLog[T]):
    """
    A wrapper providing a Pythonic interface to a time-indexed log.
    Refactored for Async-First architecture (v2.0).
    """

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

    async def range(
        self,
        start: float | None = None,
        end: float | None = None,
        limit: int | None = None,
    ) -> list[LogEntry[T]]:
        """
        Retrieves a list of log entries within a time range.
        """
        query = "SELECT timestamp, data FROM __beaver_logs__ WHERE log_name = ?"
        params = [self._name]

        if start is not None:
            query += " AND timestamp >= ?"
            params.append(start)

        if end is not None:
            query += " AND timestamp <= ?"
            params.append(end)

        query += " ORDER BY timestamp ASC"

        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)

        cursor = await self.connection.execute(query, tuple(params))
        rows = await cursor.fetchall()

        return [
            LogEntry(timestamp=row["timestamp"], data=self._deserialize(row["data"]))
            for row in rows
        ]

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

    async def count(self) -> int:
        """Returns the total number of entries in the log."""
        cursor = await self.connection.execute(
            "SELECT COUNT(*) FROM __beaver_logs__ WHERE log_name = ?", (self._name,)
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    @emits("clear", payload=lambda *args, **kwargs: dict())
    @atomic
    async def clear(self):
        """Clears all entries in this log."""
        await self.connection.execute(
            "DELETE FROM __beaver_logs__ WHERE log_name = ?", (self._name,)
        )

    async def dump(self, fp: IO[str] | None = None) -> dict | None:
        """
        Dumps the entire log to a JSON-compatible object.
        """
        # Retrieve all items
        entries = await self.range()

        items_list = []
        for entry in entries:
            val = entry.data
            if self._model and isinstance(val, BaseModel):
                val = json.loads(val.model_dump_json())

            items_list.append({"timestamp": entry.timestamp, "data": val})

        dump_obj = {
            "metadata": {
                "type": "Log",
                "name": self._name,
                "count": len(items_list),
            },
            "items": items_list,
        }

        if fp:
            json.dump(dump_obj, fp, indent=2)
            return None

        return dump_obj

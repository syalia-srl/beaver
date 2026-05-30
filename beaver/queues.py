import asyncio
import json
import time
from datetime import datetime, timezone
from typing import (
    IO,
)

from pydantic import BaseModel

from .api import expose, local_only
from .manager import AsyncBeaverBase, atomic, emits
from .interfaces import QueueItem, IAsyncBeaverQueue


class AsyncBeaverQueue[T: BaseModel](AsyncBeaverBase[T], IAsyncBeaverQueue[T]):
    """
    A wrapper providing a Pythonic interface to a persistent, multi-process
    producer-consumer priority queue.
    Refactored for Async-First architecture (v2.0).
    """

    @expose(
        path="/put",
        method="POST",
        cli_name="put",
        cli_help="Put an item in the queue.",
        body_param="data",
    )
    @emits("put", payload=lambda *args, **kwargs: dict())
    @atomic
    async def put(self, data: T, priority: float):
        """
        Adds an item to the queue with a specific priority.
        """
        await self.connection.execute(
            "INSERT INTO __beaver_priority_queues__ (queue_name, priority, timestamp, data) VALUES (?, ?, ?, ?)",
            (self._name, priority, time.time(), self._serialize(data)),
        )

    async def _get_item_atomically(self, pop: bool = True) -> QueueItem[T] | None:
        """
        Performs a single, atomic attempt to retrieve and remove the
        highest-priority item from the queue.
        """
        # We need a transaction to ensure we don't peek/get an item that someone else steals
        # Note: If called from peek/get, they might handle locking via @atomic or logic.
        # Since this helper is used inside @atomic methods, we just need execution.

        cursor = await self.connection.execute(
            """
            SELECT rowid, priority, timestamp, data
            FROM __beaver_priority_queues__
            WHERE queue_name = ?
            ORDER BY priority ASC, timestamp ASC
            LIMIT 1
            """,
            (self._name,),
        )
        result = await cursor.fetchone()

        if result is None:
            return None

        rowid, priority, timestamp, data = result

        if pop:
            await self.connection.execute(
                "DELETE FROM __beaver_priority_queues__ WHERE rowid = ?", (rowid,)
            )

        return QueueItem(
            priority=priority, timestamp=timestamp, data=self._deserialize(data)
        )

    @expose(
        path="/peek", method="GET", cli_name="peek", cli_help="Peek at the next item."
    )
    @atomic
    async def peek(self) -> QueueItem[T] | None:
        """
        Retrieves the first item of the queue without removing it.
        """
        return await self._get_item_atomically(pop=False)

    @atomic
    async def _try_pop_atomic(self) -> QueueItem[T] | None:
        """Helper to check and pop one item under lock."""
        return await self._get_item_atomically(pop=True)

    async def _get_loop_impl(self, block: bool, timeout: float | None) -> QueueItem[T]:
        """
        The polling loop. It acquires the lock only briefly during the check,
        allowing producers to interleave 'put' operations while we wait.
        """
        # 1. Non-blocking fast path
        if not block:
            item = await self._try_pop_atomic()
            if item is None:
                raise IndexError("get from an empty queue.")
            return item

        # 2. Blocking loop
        start_time = time.time()
        while True:
            item = await self._try_pop_atomic()

            if item is not None:
                return item

            if timeout is not None and (time.time() - start_time) > timeout:
                raise TimeoutError("Timeout expired while waiting for an item.")

            # Yield control to allow producers to acquire the lock and put items
            await asyncio.sleep(0.1)

    # We override the public get to use the loop implementation
    # NOTE: We do NOT decorate this with @atomic, as it manages its own locking scope.
    @expose(
        path="/get",
        method="POST",
        cli_name="get",
        cli_help="Get and remove the next item.",
    )
    @emits("get", payload=lambda *args, **kwargs: dict())
    async def get(
        self, block: bool = True, timeout: float | None = None
    ) -> QueueItem[T]:
        return await self._get_loop_impl(block, timeout)

    @expose(
        path="/count",
        method="GET",
        cli_name="count",
        cli_help="Return the number of items.",
    )
    async def count(self) -> int:
        cursor = await self.connection.execute(
            "SELECT COUNT(*) FROM __beaver_priority_queues__ WHERE queue_name = ?",
            (self._name,),
        )
        count = await cursor.fetchone()
        return count[0] if count else 0

    @expose(path="/clear", method="POST", cli_name="clear", cli_help="Clear all items.")
    async def clear(self):
        await self.connection.execute(
            "DELETE FROM __beaver_priority_queues__ WHERE queue_name = ?",
            (self._name,),
        )

    # --- Iterators ---

    async def __aiter__(self):
        cursor = await self.connection.execute(
            """
            SELECT priority, timestamp, data
            FROM __beaver_priority_queues__
            WHERE queue_name = ?
            ORDER BY priority ASC, timestamp ASC
            """,
            (self._name,),
        )
        async for row in cursor:
            yield QueueItem(
                priority=row["priority"],
                timestamp=row["timestamp"],
                data=self._deserialize(row["data"]),
            )

    async def _iter_dump_items(self):
        async for item in self:
            data = item.data
            if self._model and isinstance(data, BaseModel):
                data = json.loads(data.model_dump_json())
            yield {
                "priority": item.priority,
                "timestamp": item.timestamp,
                "data": data,
            }

    @local_only(
        "queue.dump() is only available on local databases (no chunked transfer yet)"
    )
    async def dump(
        self,
        fp: IO[str] | None = None,
        format: str = "json",
        indent: int = 2,
    ) -> dict | None:
        if format == "json":
            items_list = [item async for item in self._iter_dump_items()]
            metadata = {
                "type": "Queue",
                "name": self._name,
                "count": len(items_list),
                "dump_date": datetime.now(timezone.utc).isoformat(),
            }
            dump_obj = {"metadata": metadata, "items": items_list}
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
        "queue.load() is only available on local databases (no chunked transfer yet)"
    )
    async def load(
        self,
        fp: IO[str],
        format: str = "json",
        strategy: str = "overwrite",
    ) -> None:
        """Loads items from a serialized queue dump (JSON or JSONL)."""
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
        # Timestamp is re-assigned by put() to preserve PQ invariants; we keep
        # priority and data which together determine ordering.
        await self.put(item["data"], priority=item["priority"])

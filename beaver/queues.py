import asyncio
import json
import time
from datetime import datetime, timezone
from typing import (
    IO,
    Iterator,
    Literal,
    NamedTuple,
    overload,
    Protocol,
    runtime_checkable,
    TYPE_CHECKING,
)

from pydantic import BaseModel

from .manager import AsyncBeaverBase, atomic, emits

if TYPE_CHECKING:
    from .core import AsyncBeaverDB


class QueueItem[T](NamedTuple):
    """A data class representing a single item retrieved from the queue."""

    priority: float
    timestamp: float
    data: T


@runtime_checkable
class IBeaverQueue[T: BaseModel](Protocol):
    """
    The Synchronous Protocol exposed to the user via BeaverBridge.
    """

    def put(self, data: T, priority: float) -> None: ...

    def peek(self) -> QueueItem[T] | None: ...

    # Overloads for get
    @overload
    def get(
        self, block: Literal[True] = True, timeout: float | None = None
    ) -> QueueItem[T]: ...
    @overload
    def get(self, block: Literal[False]) -> QueueItem[T]: ...

    def clear(self) -> None: ...
    def count(self) -> int: ...
    def dump(self, fp: IO[str] | None = None) -> dict | None: ...

    def __len__(self) -> int: ...
    def __iter__(self) -> Iterator[QueueItem[T]]: ...
    def __bool__(self) -> bool: ...


class AsyncBeaverQueue[T: BaseModel](AsyncBeaverBase[T]):
    """
    A wrapper providing a Pythonic interface to a persistent, multi-process
    producer-consumer priority queue.
    Refactored for Async-First architecture (v2.0).
    """

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
    @emits("get", payload=lambda *args, **kwargs: dict())
    async def get(
        self, block: bool = True, timeout: float | None = None
    ) -> QueueItem[T]:
        return await self._get_loop_impl(block, timeout)

    async def count(self) -> int:
        cursor = await self.connection.execute(
            "SELECT COUNT(*) FROM __beaver_priority_queues__ WHERE queue_name = ?",
            (self._name,),
        )
        count = await cursor.fetchone()
        return count[0] if count else 0

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

    async def dump(self, fp: IO[str] | None = None) -> dict | None:
        items_list = []
        async for item in self:
            data = item.data
            if self._model and isinstance(data, BaseModel):
                data = json.loads(data.model_dump_json())

            items_list.append(
                {"priority": item.priority, "timestamp": item.timestamp, "data": data}
            )

        metadata = {
            "type": "Queue",
            "name": self._name,
            "count": len(items_list),
            "dump_date": datetime.now(timezone.utc).isoformat(),
        }

        dump_obj = {"metadata": metadata, "items": items_list}

        if fp:
            json.dump(dump_obj, fp, indent=2)
            return None

        return dump_obj

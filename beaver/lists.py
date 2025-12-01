import json
from typing import (
    Union,
    IO,
)
from datetime import datetime, timezone

from pydantic import BaseModel

from .manager import AsyncBeaverBase, atomic, emits
from .interfaces import IAsyncBeaverList


class AsyncBeaverList[T: BaseModel](AsyncBeaverBase[T], IAsyncBeaverList[T]):
    """
    A wrapper providing a Pythonic, persistent list in the database.
    Refactored for Async-First architecture (v2.0).
    """

    async def _get_dump_object(self) -> dict:
        items = []
        async for item in self:
            item_value = item
            if self._model and isinstance(item, BaseModel):
                item_value = json.loads(item.model_dump_json())
            items.append(item_value)

        metadata = {
            "type": "List",
            "name": self._name,
            "count": len(items),
            "dump_date": datetime.now(timezone.utc).isoformat(),
        }
        return {"metadata": metadata, "items": items}

    async def dump(self, fp: IO[str] | None = None) -> dict | None:
        """
        Dumps the entire contents of the list to a JSON-compatible object.
        """
        # We can acquire the public lock for consistency during dump
        async with self:
            dump_object = await self._get_dump_object()

        if fp:
            json.dump(dump_object, fp, indent=2)
            return None
        return dump_object

    async def count(self) -> int:
        """Returns the number of items in the list."""
        cursor = await self.connection.execute(
            "SELECT COUNT(*) FROM __beaver_lists__ WHERE list_name = ?", (self._name,)
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    @atomic
    async def get(self, index: Union[int, slice]) -> T | list[T]:
        """
        Retrieves an item or slice from the list.
        Mapped from __getitem__ by the Bridge.
        """
        # Handle Slice
        if isinstance(index, slice):
            # We need the length to calculate indices
            list_len = await self.count()
            start, stop, step = index.indices(list_len)

            if step != 1:
                raise ValueError("Slicing with a step is not supported.")

            limit = stop - start
            if limit <= 0:
                return []

            cursor = await self.connection.execute(
                "SELECT item_value FROM __beaver_lists__ WHERE list_name = ? ORDER BY item_order ASC LIMIT ? OFFSET ?",
                (self._name, limit, start),
            )
            results = [
                self._deserialize(row["item_value"]) for row in await cursor.fetchall()
            ]
            return results

        # Handle Integer
        elif isinstance(index, int):
            list_len = await self.count()
            if index < -list_len or index >= list_len:
                raise IndexError("List index out of range.")

            offset = index if index >= 0 else list_len + index

            cursor = await self.connection.execute(
                "SELECT item_value FROM __beaver_lists__ WHERE list_name = ? ORDER BY item_order ASC LIMIT 1 OFFSET ?",
                (self._name, offset),
            )
            result = await cursor.fetchone()
            if not result:
                raise IndexError("List index out of range.")

            return self._deserialize(result["item_value"])

        else:
            raise TypeError("List indices must be integers or slices.")

    @emits("set", payload=lambda index, *args, **kwargs: dict(index=index))
    @atomic
    async def set(self, index: int, value: T):
        """
        Sets the value of an item at a specific index.
        Mapped from __setitem__ by the Bridge.
        """
        if not isinstance(index, int):
            raise TypeError("List indices must be integers.")

        list_len = await self.count()
        if index < -list_len or index >= list_len:
            raise IndexError("List index out of range.")

        offset = index if index >= 0 else list_len + index

        # Find the rowid of the item to update
        cursor = await self.connection.execute(
            "SELECT rowid FROM __beaver_lists__ WHERE list_name = ? ORDER BY item_order ASC LIMIT 1 OFFSET ?",
            (self._name, offset),
        )
        result = await cursor.fetchone()
        if not result:
            raise IndexError("List index out of range during update.")

        rowid_to_update = result["rowid"]

        # Update the value
        await self.connection.execute(
            "UPDATE __beaver_lists__ SET item_value = ? WHERE rowid = ?",
            (self._serialize(value), rowid_to_update),
        )

    @emits("del", payload=lambda index, *args, **kwargs: dict(index=index))
    @atomic
    async def delete(self, index: int):
        """
        Deletes an item at a specific index.
        Mapped from __delitem__ by the Bridge.
        """
        if not isinstance(index, int):
            raise TypeError("List indices must be integers.")

        list_len = await self.count()
        if index < -list_len or index >= list_len:
            raise IndexError("List index out of range.")

        offset = index if index >= 0 else list_len + index

        # Find rowid
        cursor = await self.connection.execute(
            "SELECT rowid FROM __beaver_lists__ WHERE list_name = ? ORDER BY item_order ASC LIMIT 1 OFFSET ?",
            (self._name, offset),
        )
        result = await cursor.fetchone()
        if not result:
            raise IndexError("List index out of range during delete.")

        rowid_to_delete = result["rowid"]

        await self.connection.execute(
            "DELETE FROM __beaver_lists__ WHERE rowid = ?", (rowid_to_delete,)
        )

    # --- Iterators ---

    async def __aiter__(self):
        """Async iterator for the list."""
        cursor = await self.connection.execute(
            "SELECT item_value FROM __beaver_lists__ WHERE list_name = ? ORDER BY item_order ASC",
            (self._name,),
        )
        async for row in cursor:
            yield self._deserialize(row["item_value"])

    async def contains(self, value: T) -> bool:
        """Checks for existence of an item."""
        serialized = self._serialize(value)
        cursor = await self.connection.execute(
            "SELECT 1 FROM __beaver_lists__ WHERE list_name = ? AND item_value = ? LIMIT 1",
            (self._name, serialized),
        )
        return await cursor.fetchone() is not None

    async def _get_order_at_index(self, index: int) -> float:
        """Helper to get the float item_order at a specific index."""
        cursor = await self.connection.execute(
            "SELECT item_order FROM __beaver_lists__ WHERE list_name = ? ORDER BY item_order ASC LIMIT 1 OFFSET ?",
            (self._name, index),
        )
        result = await cursor.fetchone()

        if result:
            return result[0]
        raise IndexError(f"{index} out of range.")

    @emits("push", payload=lambda *args, **kwargs: dict())
    @atomic
    async def push(self, value: T):
        """Pushes an item to the end of the list."""
        cursor = await self.connection.execute(
            "SELECT MAX(item_order) FROM __beaver_lists__ WHERE list_name = ?",
            (self._name,),
        )
        row = await cursor.fetchone()
        max_order = row[0] if row and row[0] is not None else 0.0
        new_order = max_order + 1.0

        await self.connection.execute(
            "INSERT INTO __beaver_lists__ (list_name, item_order, item_value) VALUES (?, ?, ?)",
            (self._name, new_order, self._serialize(value)),
        )

    @emits("prepend", payload=lambda *args, **kwargs: dict())
    @atomic
    async def prepend(self, value: T):
        """Prepends an item to the beginning of the list."""
        cursor = await self.connection.execute(
            "SELECT MIN(item_order) FROM __beaver_lists__ WHERE list_name = ?",
            (self._name,),
        )
        row = await cursor.fetchone()
        min_order = row[0] if row and row[0] is not None else 0.0
        new_order = min_order - 1.0

        await self.connection.execute(
            "INSERT INTO __beaver_lists__ (list_name, item_order, item_value) VALUES (?, ?, ?)",
            (self._name, new_order, self._serialize(value)),
        )

    @emits("insert", payload=lambda index, *args, **kwargs: dict(index=index))
    @atomic
    async def insert(self, index: int, value: T):
        """Inserts an item at a specific index using float order logic."""
        list_len = await self.count()

        if index <= 0:
            await self.prepend(value)
            return
        if index >= list_len:
            await self.push(value)
            return

        # Midpoint insertion
        order_before = await self._get_order_at_index(index - 1)
        order_after = await self._get_order_at_index(index)
        new_order = order_before + (order_after - order_before) / 2.0

        await self.connection.execute(
            "INSERT INTO __beaver_lists__ (list_name, item_order, item_value) VALUES (?, ?, ?)",
            (self._name, new_order, self._serialize(value)),
        )

    @emits("pop", payload=lambda *args, **kwargs: dict())
    @atomic
    async def pop(self) -> T | None:
        """Removes and returns the last item."""
        cursor = await self.connection.execute(
            "SELECT rowid, item_value FROM __beaver_lists__ WHERE list_name = ? ORDER BY item_order DESC LIMIT 1",
            (self._name,),
        )
        result = await cursor.fetchone()
        if not result:
            return None

        rowid_to_delete, value_to_return = result
        await self.connection.execute(
            "DELETE FROM __beaver_lists__ WHERE rowid = ?", (rowid_to_delete,)
        )
        return self._deserialize(value_to_return)

    @emits("deque", payload=lambda *args, **kwargs: dict())
    @atomic
    async def deque(self) -> T | None:
        """Removes and returns the first item."""
        cursor = await self.connection.execute(
            "SELECT rowid, item_value FROM __beaver_lists__ WHERE list_name = ? ORDER BY item_order ASC LIMIT 1",
            (self._name,),
        )
        result = await cursor.fetchone()
        if not result:
            return None

        rowid_to_delete, value_to_return = result
        await self.connection.execute(
            "DELETE FROM __beaver_lists__ WHERE rowid = ?", (rowid_to_delete,)
        )
        return self._deserialize(value_to_return)

    @emits("clear", payload=lambda *args, **kwargs: dict())
    @atomic
    async def clear(self):
        """Atomically removes all items."""
        await self.connection.execute(
            "DELETE FROM __beaver_lists__ WHERE list_name = ?",
            (self._name,),
        )

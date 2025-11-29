from base64 import b64encode
import json
from typing import (
    IO,
    Any,
    Iterator,
    Tuple,
    Protocol,
    runtime_checkable,
    TYPE_CHECKING,
    overload,
)

from pydantic import BaseModel

from .manager import AsyncBeaverBase, atomic, emits
from .interfaces import IAsyncBeaverBlob, BlobItem

if TYPE_CHECKING:
    from .core import AsyncBeaverDB


class AsyncBeaverBlob[T: BaseModel](AsyncBeaverBase[T], IAsyncBeaverBlob[T]):
    """
    A wrapper providing a dictionary-like interface for storing binary blobs
    with optional metadata.
    Refactored for Async-First architecture (v2.0).
    """

    @emits("put", payload=lambda key, *args, **kwargs: dict(key=key))
    @atomic
    async def put(self, key: str, data: bytes, metadata: dict | None = None):
        """
        Stores binary data under a key, optionally with JSON metadata.
        """
        if not isinstance(data, bytes):
            raise TypeError("Blob data must be bytes.")

        meta_json = json.dumps(metadata) if metadata is not None else None

        await self.connection.execute(
            """
            INSERT OR REPLACE INTO __beaver_blobs__
            (store_name, key, data, metadata)
            VALUES (?, ?, ?, ?)
            """,
            (self._name, key, data, meta_json),
        )

    @atomic
    async def fetch(self, key: str) -> BlobItem:
        """
        Retrieves the full BlobItem (data + metadata).
        Raises KeyError if missing.
        """
        cursor = await self.connection.execute(
            "SELECT data, metadata FROM __beaver_blobs__ WHERE store_name = ? AND key = ?",
            (self._name, key),
        )
        row = await cursor.fetchone()

        if row is None:
            raise KeyError(f"Key '{key}' not found in blob store '{self._name}'")

        meta = json.loads(row["metadata"]) if row["metadata"] else None
        return BlobItem(key=key, data=row["data"], metadata=meta)

    @atomic
    async def get(self, key: str) -> bytes:
        """
        Retrieves just the binary data for a key.
        Mapped from __getitem__ via the Bridge.
        """
        cursor = await self.connection.execute(
            "SELECT data FROM __beaver_blobs__ WHERE store_name = ? AND key = ?",
            (self._name, key),
        )
        row = await cursor.fetchone()

        if row is None:
            raise KeyError(f"Key '{key}' not found in blob store '{self._name}'")

        return row["data"]

    @emits("set", payload=lambda key, *args, **kwargs: dict(key=key))
    @atomic
    async def set(self, key: str, data: bytes):
        """
        Alias for put(key, data) without metadata.
        Mapped from __setitem__ via the Bridge.
        """
        await self.put(key, data)

    @emits("del", payload=lambda key, *args, **kwargs: dict(key=key))
    @atomic
    async def delete(self, key: str):
        """
        Deletes a blob.
        Mapped from __delitem__ via the Bridge.
        """
        cursor = await self.connection.execute(
            "DELETE FROM __beaver_blobs__ WHERE store_name = ? AND key = ?",
            (self._name, key),
        )
        if cursor.rowcount == 0:
            raise KeyError(f"Key '{key}' not found in blob store '{self._name}'")

    async def count(self) -> int:
        cursor = await self.connection.execute(
            "SELECT COUNT(*) FROM __beaver_blobs__ WHERE store_name = ?", (self._name,)
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def contains(self, key: str) -> bool:
        cursor = await self.connection.execute(
            "SELECT 1 FROM __beaver_blobs__ WHERE store_name = ? AND key = ? LIMIT 1",
            (self._name, key),
        )
        return await cursor.fetchone() is not None

    @emits("clear", payload=lambda *args, **kwargs: dict())
    @atomic
    async def clear(self):
        await self.connection.execute(
            "DELETE FROM __beaver_blobs__ WHERE store_name = ?",
            (self._name,),
        )

    # --- Iterators ---

    async def __aiter__(self):
        async for key in self.keys():
            yield key

    async def keys(self):
        cursor = await self.connection.execute(
            "SELECT key FROM __beaver_blobs__ WHERE store_name = ?", (self._name,)
        )
        async for row in cursor:
            yield row["key"]

    async def items(self):
        cursor = await self.connection.execute(
            "SELECT key, data FROM __beaver_blobs__ WHERE store_name = ?", (self._name,)
        )
        async for row in cursor:
            yield (row["key"], row["data"])

    async def dump(
        self, fp: IO[str] | None = None, *, payload: bool = False
    ) -> dict | None:
        """
        Dumps blobs to a JSON-compatible object.
        Note: Binary data is serialized to base-64 strings, *only* when payload=True.
        Otherwise, only metadata is dumped.
        """
        items = []
        async for key in self.keys():
            # For blobs, dumping full content to JSON is dangerous (memory).
            # We dump metadata primarily.
            try:
                item = await self.fetch(key)
                items.append(
                    {
                        "key": key,
                        "metadata": item.metadata,
                        "size": len(item.data),
                        "payload": (
                            b64encode(item.data).decode("utf-8") if payload else None
                        ),
                    }
                )
            except KeyError:
                continue

        dump_obj = {
            "metadata": {
                "type": "BlobStore",
                "name": self._name,
                "count": len(items),
            },
            "items": items,
        }

        if fp:
            json.dump(dump_obj, fp, indent=2)
            return None

        return dump_obj

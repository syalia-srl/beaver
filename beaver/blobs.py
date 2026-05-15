from base64 import b64decode, b64encode
import json
from typing import (
    IO,
    TYPE_CHECKING,
)

from pydantic import BaseModel

from .manager import AsyncBeaverBase, atomic, emits
from .interfaces import IAsyncBeaverBlob, BlobItem


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

    async def _iter_dump_items(self, payload: bool):
        async for key in self.keys():
            try:
                item = await self.fetch(key)
            except KeyError:
                continue
            yield {
                "key": key,
                "metadata": item.metadata,
                "size": len(item.data),
                "payload": (b64encode(item.data).decode("utf-8") if payload else None),
            }

    async def dump(
        self,
        fp: IO[str] | None = None,
        format: str = "json",
        indent: int = 2,
        *,
        payload: bool = False,
    ) -> dict | None:
        """
        Dumps blobs to a JSON-compatible object.
        Binary data is base64-encoded only when payload=True; otherwise the
        dump is metadata-only and non-restorable. JSONL always forces
        payload=True (a streaming metadata-only dump has no use case).
        """
        if format == "json":
            items = [item async for item in self._iter_dump_items(payload=payload)]
            dump_obj = {
                "metadata": {
                    "type": "BlobStore",
                    "name": self._name,
                    "count": len(items),
                },
                "items": items,
            }
            if fp:
                json.dump(dump_obj, fp, indent=indent)
                return None
            return dump_obj
        if format == "jsonl":
            if fp is None:
                raise ValueError("JSONL format requires fp.")
            async for item in self._iter_dump_items(payload=True):
                fp.write(json.dumps(item) + "\n")
            return None
        raise ValueError(f"Unsupported format: {format!r}. Use 'json' or 'jsonl'.")

    async def load(
        self,
        fp: IO[str],
        format: str = "json",
        strategy: str = "overwrite",
    ) -> None:
        """
        Loads blobs from a serialized dump (JSON or JSONL).
        Requires payload to be present — metadata-only dumps cannot restore data.
        """
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
        if item.get("payload") is None:
            raise ValueError(
                f"Cannot load blob {item.get('key')!r}: dump has no payload. "
                "Re-dump the source with payload=True to make it restorable."
            )
        raw = b64decode(item["payload"])
        await self.put(item["key"], raw, metadata=item.get("metadata"))

import base64
from datetime import datetime, timezone
import json
from typing import IO, Iterator, NamedTuple, Optional, overload
from .types import JsonSerializable
from .manager import ManagerBase, synced


class Blob[M](NamedTuple):
    """A data class representing a single blob retrieved from the store."""

    key: str
    data: bytes
    metadata: Optional[M]


class BlobManager[M: JsonSerializable](ManagerBase[M]):
    """A wrapper providing a Pythonic interface to a blob store in the database."""

    @synced
    def get(self, key: str) -> Optional[Blob[M]]:
        """Retrieves a blob from the store."""
        # --- 1. Check cache first ---
        cached_blob = self.cache.get(key)
        if cached_blob is not None:
            return cached_blob  # Cache HIT

        # --- 2. Cache MISS ---
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT data, metadata FROM beaver_blobs WHERE store_name = ? AND key = ?",
            (self._name, key),
        )
        result = cursor.fetchone()
        cursor.close()

        if result is None:
            return None

        data, metadata_json = result
        metadata = self._deserialize(metadata_json) if metadata_json else None

        # --- 3. Create object and populate cache ---
        blob_obj = Blob(key=key, data=data, metadata=metadata)
        self.cache.set(key, blob_obj)

        return blob_obj

    @synced
    def put(self, key: str, data: bytes, metadata: Optional[M] = None):
        """Stores or replaces a blob in the store."""
        if not isinstance(data, bytes):
            raise TypeError("Blob data must be of type bytes.")

        metadata_json = self._serialize(metadata) if metadata else None

        with self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO beaver_blobs (store_name, key, data, metadata) VALUES (?, ?, ?, ?)",
                (self._name, key, data, metadata_json),
            )

        # --- 1. Write-through to cache ---
        # Create the object we know we just stored
        blob_obj = Blob(key=key, data=data, metadata=metadata)
        self.cache.set(key, blob_obj)

    @synced
    def delete(self, key: str):
        """Deletes a blob from the store."""
        # --- 1. Evict from cache ---
        self.cache.pop(key)

        cursor = self.connection.cursor()
        cursor.execute(
            "DELETE FROM beaver_blobs WHERE store_name = ? AND key = ?",
            (self._name, key),
        )
        if cursor.rowcount == 0:
            raise KeyError(f"Key '{key}' not found in blob store '{self._name}'")

    def __contains__(self, key: str) -> bool:
        """
        Checks if a key exists in the blob store (e.g., `key in blobs`).
        """
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT 1 FROM beaver_blobs WHERE store_name = ? AND key = ? LIMIT 1",
            (self._name, key),
        )
        result = cursor.fetchone()
        cursor.close()
        return result is not None

    def __iter__(self) -> Iterator[str]:
        """Returns an iterator over the keys in the blob store."""
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT key FROM beaver_blobs WHERE store_name = ?", (self._name,)
        )
        for row in cursor:
            yield row["key"]
        cursor.close()

    def __len__(self) -> int:
        """Returns the number of blobs in the store."""
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM beaver_blobs WHERE store_name = ?",
            (self._name,)
        )
        count = cursor.fetchone()[0]
        cursor.close()
        return count

    def __repr__(self) -> str:
        return f"BlobManager(name='{self._name}')"

    def _get_dump_object(self) -> dict:
        """Builds the JSON-compatible dump object."""

        items_list = []
        # __iter__ yields keys, so we get each blob
        for key in self:
            blob = self.get(key)
            if blob:
                metadata = blob.metadata

                # Handle model instances in metadata
                if self._model and isinstance(metadata, JsonSerializable):
                    metadata = json.loads(metadata.model_dump_json())

                # Encode binary data to a base64 string
                data_b64 = base64.b64encode(blob.data).decode('utf-8')

                items_list.append({
                    "key": blob.key,
                    "metadata": metadata,
                    "data_b64": data_b64
                })

        metadata = {
            "type": "BlobStore",
            "name": self._name,
            "count": len(items_list),
            "dump_date": datetime.now(timezone.utc).isoformat()
        }

        return {
            "metadata": metadata,
            "items": items_list
        }

    @overload
    def dump(self) -> dict:
        pass

    @overload
    def dump(self, fp: IO[str]) -> None:
        pass

    def dump(self, fp: IO[str] | None = None) -> dict | None:
        """
        Dumps the entire contents of the blob store to a JSON-compatible
        Python object or a file-like object.

        Args:
            fp: A file-like object opened in text mode (e.g., with 'w').
                If provided, the JSON dump will be written to this file.
                If None (default), the dump will be returned as a dictionary.

        Returns:
            A dictionary containing the dump if fp is None.
            None if fp is provided.
        """
        dump_object = self._get_dump_object()

        if fp:
            json.dump(dump_object, fp, indent=2)
            return None

        return dump_object

    @synced
    def clear(self):
        """Atomically removes all blobs from this store."""
        self.connection.execute(
            "DELETE FROM beaver_blobs WHERE store_name = ?",
            (self._name,),
        )
        # --- 1. Clear the cache ---
        self.cache.clear()

import json
import sqlite3
from typing import Any, Dict, Iterator, NamedTuple, Optional, Type, TypeVar
from .types import JsonSerializable, IDatabase
from .locks import LockManager


class Blob[M](NamedTuple):
    """A data class representing a single blob retrieved from the store."""

    key: str
    data: bytes
    metadata: M


class BlobManager[M]:
    """A wrapper providing a Pythonic interface to a blob store in the database."""

# In beaver/blobs.py, inside class BlobManager[M]:
    def __init__(self, name: str, db: IDatabase, model: Type[M] | None = None):
        self._name = name
        self._db = db
        self._model = model
        lock_name = f"__lock__blob__{name}"
        self._lock = LockManager(db, lock_name)

    def _serialize(self, value: M) -> str | None:
        """Serializes the given value to a JSON string."""
        if value is None:
            return None
        if isinstance(value, JsonSerializable):
            return value.model_dump_json()

        return json.dumps(value)

    def _deserialize(self, value: str) -> M:
        """Deserializes a JSON string into the specified model or a generic object."""
        if self._model:
            return self._model.model_validate_json(value)

        return json.loads(value)

    def put(self, key: str, data: bytes, metadata: Optional[M] = None):
        """
        Stores or replaces a blob in the store.

        Args:
            key: The unique string identifier for the blob.
            data: The binary data to store.
            metadata: Optional JSON-serializable dictionary for metadata.
        """
        if not isinstance(data, bytes):
            raise TypeError("Blob data must be of type bytes.")

        metadata_json = self._serialize(metadata) if metadata else None

        with self._db.connection:
            self._db.connection.execute(
                "INSERT OR REPLACE INTO beaver_blobs (store_name, key, data, metadata) VALUES (?, ?, ?, ?)",
                (self._name, key, data, metadata_json),
            )

    def get(self, key: str) -> Optional[Blob[M]]:
        """
        Retrieves a blob from the store.

        Args:
            key: The unique string identifier for the blob.

        Returns:
            A Blob object containing the data and metadata, or None if the key is not found.
        """
        cursor = self._db.connection.cursor()
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

        return Blob(key=key, data=data, metadata=metadata)

    def delete(self, key: str):
        """
        Deletes a blob from the store.

        Raises:
            KeyError: If the key does not exist in the store.
        """
        with self._db.connection:
            cursor = self._db.connection.cursor()
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
        cursor = self._db.connection.cursor()
        cursor.execute(
            "SELECT 1 FROM beaver_blobs WHERE store_name = ? AND key = ? LIMIT 1",
            (self._name, key),
        )
        result = cursor.fetchone()
        cursor.close()
        return result is not None

    def __iter__(self) -> Iterator[str]:
        """Returns an iterator over the keys in the blob store."""
        cursor = self._db.connection.cursor()
        cursor.execute(
            "SELECT key FROM beaver_blobs WHERE store_name = ?", (self._name,)
        )
        for row in cursor:
            yield row["key"]
        cursor.close()

    def __len__(self) -> int:
        """Returns the number of blobs in the store."""
        cursor = self._db.connection.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM beaver_blobs WHERE store_name = ?",
            (self._name,)
        )
        count = cursor.fetchone()[0]
        cursor.close()
        return count

    def __repr__(self) -> str:
        return f"BlobManager(name='{self._name}')"

    def acquire(
        self,
        timeout: Optional[float] = None,
        lock_ttl: Optional[float] = None,
        poll_interval: Optional[float] = None,
    ) -> "BlobManager[M]":
        """
        Acquires an inter-process lock on this blob store, blocking until acquired.

        Parameters override the default settings of the underlying LockManager.
        """
        self._lock.acquire(
            timeout=timeout,
            lock_ttl=lock_ttl,
            poll_interval=poll_interval
        )
        return self

    def release(self):
        """
        Releases the inter-process lock on this blob store.
        """
        self._lock.release()

    def __enter__(self) -> "BlobManager[M]":
        """Acquires the lock upon entering a 'with' statement."""
        return self.acquire()

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Releases the lock when exiting a 'with' statement."""
        self.release()

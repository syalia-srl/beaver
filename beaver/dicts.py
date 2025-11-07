from datetime import datetime, timezone
import json
import sqlite3
import time
from typing import IO, Any, Iterator, Tuple, Type, Optional, overload

from beaver.cache import ICache
from .types import JsonSerializable, IDatabase
from .locks import LockManager
from .manager import ManagerBase, synced

class DictManager[T: JsonSerializable](ManagerBase[T]):
    """A wrapper providing a Pythonic interface to a dictionary in the database."""

    def _get_dump_object(self) -> dict:
        """Builds the JSON-compatible dump object."""
        items = []

        for k, v in self.items():
            item_value = v
            # Check if a model is defined and the value is a model instance
            if self._model and isinstance(v, JsonSerializable):
                # Use the model's serializer to get its string representation,
                # then parse that string back into a dict.
                # This ensures the dump contains serializable dicts, not model objects.
                item_value = json.loads(v.model_dump_json())

            items.append({"key": k, "value": item_value})

        metadata = {
            "type": "Dict",
            "name": self._name,
            "count": len(items),
            "dump_date": datetime.now(timezone.utc).isoformat(),
        }

        return {"metadata": metadata, "items": items}

    @overload
    def dump(self) -> dict:
        pass

    @overload
    def dump(self, fp: IO[str]) -> None:
        pass

    def dump(self, fp: IO[str] | None = None) -> dict | None:
        """
        Dumps the entire contents of the dictionary to a JSON-compatible
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

    def set(self, key: str, value: T, ttl_seconds: float | None = None):
        """Sets a value for a key, with an optional TTL."""
        self.__setitem__(key, value, ttl_seconds=ttl_seconds)

    @synced
    def __setitem__(self, key: str, value: T, ttl_seconds: float | None = None):
        """Sets a value for a key (e.g., `my_dict[key] = value`)."""
        expires_at = None

        if ttl_seconds is not None:
            if not isinstance(ttl_seconds, (int, float)) or ttl_seconds <= 0:
                raise ValueError("ttl_seconds must be a positive integer or float.")

            expires_at = time.time() + ttl_seconds

        self.connection.execute(
            "INSERT OR REPLACE INTO beaver_dicts (dict_name, key, value, expires_at) VALUES (?, ?, ?, ?)",
            (self._name, key, self._serialize(value), expires_at),
        )

        self.cache.set(key, (value, expires_at))

    def get(self, key: str, default: Any = None) -> T | Any:
        """Gets a value for a key, with a default if it doesn't exist or is expired."""
        try:
            return self[key]
        except KeyError:
            return default

    @synced
    def __getitem__(self, key: str) -> T:
        """Retrieves a value for a given key, raising KeyError if expired."""
        cache = self.cache

        # Cache HIT
        if (cached := cache.get(key)) is not None:
            value, expires_at = cached

            if expires_at is None or time.time() < expires_at:
                return value
            else:
                cache.pop(key)
                raise KeyError(
                    f"Key '{key}' not found in dictionary '{self._name}' (expired)"
                )

        # Cache MISS
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT value, expires_at FROM beaver_dicts WHERE dict_name = ? AND key = ?",
            (self._name, key),
        )
        result = cursor.fetchone()

        if result is None:
            cursor.close()
            raise KeyError(f"Key '{key}' not found in dictionary '{self._name}'")

        value, expires_at = result["value"], result["expires_at"]

        if expires_at is not None and time.time() > expires_at:
            # Expired: delete the key and raise KeyError
            with self.connection:
                cursor.execute(
                    "DELETE FROM beaver_dicts WHERE dict_name = ? AND key = ?",
                    (self._name, key),
                )
            cursor.close()

            # Evict from cache if it was there
            cache.pop(f"dict:{self._name}.{key}")

            raise KeyError(
                f"Key '{key}' not found in dictionary '{self._name}' (expired)"
            )

        cursor.close()
        result = self._deserialize(value)

        # Update cache
        cache.set(key, (result, expires_at))
        return result

    def pop(self, key: str, default: Any = None) -> T | Any:
        """Deletes an item if it exists and returns its value."""
        try:
            value = self[key]
            del self[key]
            return value
        except KeyError:
            return default

    @synced
    def __delitem__(self, key: str):
        """Deletes a key-value pair (e.g., `del my_dict[key]`)."""
        cursor = self.connection.cursor()
        cursor.execute(
            "DELETE FROM beaver_dicts WHERE dict_name = ? AND key = ?",
            (self._name, key),
        )

        # Evict from cache
        self.cache.pop(key)

        if cursor.rowcount == 0:
            raise KeyError(f"Key '{key}' not found in dictionary '{self._name}'")

    def __len__(self) -> int:
        """Returns the number of items in the dictionary."""
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM beaver_dicts WHERE dict_name = ?", (self._name,)
        )
        count = cursor.fetchone()[0]
        cursor.close()
        return count

    def __iter__(self) -> Iterator[str]:
        """Returns an iterator over the keys of the dictionary."""
        return self.keys()

    def keys(self) -> Iterator[str]:
        """Returns an iterator over the dictionary's keys."""
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT key FROM beaver_dicts WHERE dict_name = ?", (self._name,)
        )
        for row in cursor:
            yield row["key"]
        cursor.close()

    def values(self) -> Iterator[T]:
        """Returns an iterator over the dictionary's values."""
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT value FROM beaver_dicts WHERE dict_name = ?", (self._name,)
        )
        for row in cursor:
            yield self._deserialize(row["value"])
        cursor.close()

    def items(self) -> Iterator[Tuple[str, T]]:
        """Returns an iterator over the dictionary's items (key-value pairs)."""
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT key, value FROM beaver_dicts WHERE dict_name = ?", (self._name,)
        )
        for row in cursor:
            yield (row["key"], self._deserialize(row["value"]))
        cursor.close()

    def __repr__(self) -> str:
        return f"DictManager(name='{self._name}')"

    def __contains__(self, key: str) -> bool:
        """Checks if a key exists in the dictionary."""
        try:
            _ = self[key]
            return True
        except KeyError:
            return False

    @synced
    def clear(self):
        """
        Atomically removes all key-value pairs from this dictionary.
        """
        self.connection.execute(
            "DELETE FROM beaver_dicts WHERE dict_name = ?",
            (self._name,),
        )

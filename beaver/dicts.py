import json
import sqlite3
import time
from typing import Any, Iterator, Tuple, Type

from .types import JsonSerializable


class DictManager[T]:
    """A wrapper providing a Pythonic interface to a dictionary in the database."""

    def __init__(self, name: str, conn: sqlite3.Connection, model: Type[T] | None = None):
        self._name = name
        self._conn = conn
        self._model = model

    def _serialize(self, value: T) -> str:
        """Serializes the given value to a JSON string."""
        if isinstance(value, JsonSerializable):
            return value.model_dump_json()

        return json.dumps(value)

    def _deserialize(self, value: str) -> T:
        """Deserializes a JSON string into the specified model or a generic object."""
        if self._model:
            return self._model.model_validate_json(value)

        return json.loads(value)

    def set(self, key: str, value: T, ttl_seconds: int | None = None):
        """Sets a value for a key, with an optional TTL."""
        self.__setitem__(key, value, ttl_seconds=ttl_seconds)

    def __setitem__(self, key: str, value: T, ttl_seconds: int | None = None):
        """Sets a value for a key (e.g., `my_dict[key] = value`)."""
        expires_at = None
        if ttl_seconds is not None:
            if not isinstance(ttl_seconds, int) or ttl_seconds <= 0:
                raise ValueError("ttl_seconds must be a positive integer.")
            expires_at = time.time() + ttl_seconds

        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO beaver_dicts (dict_name, key, value, expires_at) VALUES (?, ?, ?, ?)",
                (self._name, key, self._serialize(value), expires_at),
            )

    def get(self, key: str, default: Any = None) -> T | Any:
        """Gets a value for a key, with a default if it doesn't exist or is expired."""
        try:
            return self[key]
        except KeyError:
            return default

    def __getitem__(self, key: str) -> T:
        """Retrieves a value for a given key, raising KeyError if expired."""
        cursor = self._conn.cursor()
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
            with self._conn:
                cursor.execute(
                    "DELETE FROM beaver_dicts WHERE dict_name = ? AND key = ?",
                    (self._name, key),
                )
            cursor.close()
            raise KeyError(
                f"Key '{key}' not found in dictionary '{self._name}' (expired)"
            )

        cursor.close()
        return self._deserialize(value)

    def pop(self, key: str, default: Any = None) -> T | Any:
        """Deletes an item if it exists and returns its value."""
        try:
            value = self[key]
            del self[key]
            return value
        except KeyError:
            return default

    def __delitem__(self, key: str):
        """Deletes a key-value pair (e.g., `del my_dict[key]`)."""
        with self._conn:
            cursor = self._conn.cursor()
            cursor.execute(
                "DELETE FROM beaver_dicts WHERE dict_name = ? AND key = ?",
                (self._name, key),
            )
            if cursor.rowcount == 0:
                raise KeyError(f"Key '{key}' not found in dictionary '{self._name}'")

    def __len__(self) -> int:
        """Returns the number of items in the dictionary."""
        cursor = self._conn.cursor()
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
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT key FROM beaver_dicts WHERE dict_name = ?", (self._name,)
        )
        for row in cursor:
            yield row["key"]
        cursor.close()

    def values(self) -> Iterator[T]:
        """Returns an iterator over the dictionary's values."""
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT value FROM beaver_dicts WHERE dict_name = ?", (self._name,)
        )
        for row in cursor:
            yield self._deserialize(row["value"])
        cursor.close()

    def items(self) -> Iterator[Tuple[str, T]]:
        """Returns an iterator over the dictionary's items (key-value pairs)."""
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT key, value FROM beaver_dicts WHERE dict_name = ?", (self._name,)
        )
        for row in cursor:
            yield (row["key"], self._deserialize(row["value"]))
        cursor.close()

    def __repr__(self) -> str:
        return f"DictManager(name='{self._name}')"
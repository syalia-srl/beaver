import json
import sqlite3
from typing import Any, Iterator, Tuple


class DictWrapper:
    """A wrapper providing a Pythonic interface to a dictionary in the database."""

    def __init__(self, name: str, conn: sqlite3.Connection):
        self._name = name
        self._conn = conn

    def set(self, key: str, value: Any):
        """Sets a value for a key in the dictionary."""
        self.__setitem__(key, value)

    def __setitem__(self, key: str, value: Any):
        """Sets a value for a key (e.g., `my_dict[key] = value`)."""
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO beaver_dicts (dict_name, key, value) VALUES (?, ?, ?)",
                (self._name, key, json.dumps(value)),
            )

    def get(self, key: str, default: Any = None) -> Any:
        """Gets a value for a key, with a default if it doesn't exist."""
        try:
            return self[key]
        except KeyError:
            return default

    def __getitem__(self, key: str) -> Any:
        """Retrieves a value for a given key (e.g., `my_dict[key]`)."""
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT value FROM beaver_dicts WHERE dict_name = ? AND key = ?",
            (self._name, key),
        )
        result = cursor.fetchone()
        cursor.close()
        if result is None:
            raise KeyError(f"Key '{key}' not found in dictionary '{self._name}'")
        return json.loads(result["value"])

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

    def values(self) -> Iterator[Any]:
        """Returns an iterator over the dictionary's values."""
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT value FROM beaver_dicts WHERE dict_name = ?", (self._name,)
        )
        for row in cursor:
            yield json.loads(row["value"])
        cursor.close()

    def items(self) -> Iterator[Tuple[str, Any]]:
        """Returns an iterator over the dictionary's items (key-value pairs)."""
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT key, value FROM beaver_dicts WHERE dict_name = ?", (self._name,)
        )
        for row in cursor:
            yield (row["key"], json.loads(row["value"]))
        cursor.close()

    def __repr__(self) -> str:
        return f"DictWrapper(name='{self._name}')"

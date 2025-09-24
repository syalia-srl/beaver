import json
import sqlite3
from typing import Any, Iterator, Type, Union

from .types import JsonSerializable


class ListManager[T]:
    """A wrapper providing a Pythonic, full-featured interface to a list in the database."""

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

    def __len__(self) -> int:
        """Returns the number of items in the list (e.g., `len(my_list)`)."""
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM beaver_lists WHERE list_name = ?", (self._name,)
        )
        count = cursor.fetchone()[0]
        cursor.close()
        return count

    def __getitem__(self, key: Union[int, slice]) -> T | list[T]:
        """
        Retrieves an item or slice from the list (e.g., `my_list[0]`, `my_list[1:3]`).
        """
        if isinstance(key, slice):
            with self._conn:
                start, stop, step = key.indices(len(self))
                if step != 1:
                    raise ValueError("Slicing with a step is not supported.")

                limit = stop - start
                if limit <= 0:
                    return []

                cursor = self._conn.cursor()
                cursor.execute(
                    "SELECT item_value FROM beaver_lists WHERE list_name = ? ORDER BY item_order ASC LIMIT ? OFFSET ?",
                    (self._name, limit, start),
                )
                results = [self._deserialize(row["item_value"]) for row in cursor.fetchall()]
                cursor.close()
                return results

        elif isinstance(key, int):
            with self._conn:
                list_len = len(self)
                if key < -list_len or key >= list_len:
                    raise IndexError("List index out of range.")

                offset = key if key >= 0 else list_len + key

                cursor = self._conn.cursor()
                cursor.execute(
                    "SELECT item_value FROM beaver_lists WHERE list_name = ? ORDER BY item_order ASC LIMIT 1 OFFSET ?",
                    (self._name, offset),
                )
                result = cursor.fetchone()
                cursor.close()
                return self._deserialize(result["item_value"])

        else:
            raise TypeError("List indices must be integers or slices.")

    def __setitem__(self, key: int, value: T):
        """Sets the value of an item at a specific index (e.g., `my_list[0] = 'new'`)."""
        if not isinstance(key, int):
            raise TypeError("List indices must be integers.")

        with self._conn:
            list_len = len(self)
            if key < -list_len or key >= list_len:
                raise IndexError("List index out of range.")

            offset = key if key >= 0 else list_len + key

            cursor = self._conn.cursor()
            # Find the rowid of the item to update
            cursor.execute(
                "SELECT rowid FROM beaver_lists WHERE list_name = ? ORDER BY item_order ASC LIMIT 1 OFFSET ?",
                (self._name, offset)
            )
            result = cursor.fetchone()
            if not result:
                raise IndexError("List index out of range during update.")

            rowid_to_update = result['rowid']
            # Update the value for that specific row
            cursor.execute(
                "UPDATE beaver_lists SET item_value = ? WHERE rowid = ?",
                (self._serialize(value), rowid_to_update)
            )

    def __delitem__(self, key: int):
        """Deletes an item at a specific index (e.g., `del my_list[0]`)."""
        if not isinstance(key, int):
            raise TypeError("List indices must be integers.")

        with self._conn:
            list_len = len(self)
            if key < -list_len or key >= list_len:
                raise IndexError("List index out of range.")

            offset = key if key >= 0 else list_len + key

            cursor = self._conn.cursor()
            # Find the rowid of the item to delete
            cursor.execute(
                "SELECT rowid FROM beaver_lists WHERE list_name = ? ORDER BY item_order ASC LIMIT 1 OFFSET ?",
                (self._name, offset)
            )
            result = cursor.fetchone()
            if not result:
                raise IndexError("List index out of range during delete.")

            rowid_to_delete = result['rowid']
            # Delete that specific row
            cursor.execute("DELETE FROM beaver_lists WHERE rowid = ?", (rowid_to_delete,))

    def __iter__(self) -> Iterator[T]:
        """Returns an iterator for the list."""
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT item_value FROM beaver_lists WHERE list_name = ? ORDER BY item_order ASC",
            (self._name,)
        )
        for row in cursor:
            yield self._deserialize(row['item_value'])
        cursor.close()

    def __contains__(self, value: T) -> bool:
        """Checks for the existence of an item in the list (e.g., `'item' in my_list`)."""
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT 1 FROM beaver_lists WHERE list_name = ? AND item_value = ? LIMIT 1",
            (self._name, self._serialize(value))
        )
        result = cursor.fetchone()
        cursor.close()
        return result is not None

    def __repr__(self) -> str:
        """Returns a developer-friendly representation of the object."""
        return f"ListManager(name='{self._name}')"

    def _get_order_at_index(self, index: int) -> float:
        """Helper to get the float `item_order` at a specific index."""
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT item_order FROM beaver_lists WHERE list_name = ? ORDER BY item_order ASC LIMIT 1 OFFSET ?",
            (self._name, index),
        )
        result = cursor.fetchone()
        cursor.close()

        if result:
            return result[0]

        raise IndexError(f"{index} out of range.")

    def push(self, value: T):
        """Pushes an item to the end of the list."""
        with self._conn:
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT MAX(item_order) FROM beaver_lists WHERE list_name = ?",
                (self._name,),
            )
            max_order = cursor.fetchone()[0] or 0.0
            new_order = max_order + 1.0

            cursor.execute(
                "INSERT INTO beaver_lists (list_name, item_order, item_value) VALUES (?, ?, ?)",
                (self._name, new_order, self._serialize(value)),
            )

    def prepend(self, value: T):
        """Prepends an item to the beginning of the list."""
        with self._conn:
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT MIN(item_order) FROM beaver_lists WHERE list_name = ?",
                (self._name,),
            )
            min_order = cursor.fetchone()[0] or 0.0
            new_order = min_order - 1.0

            cursor.execute(
                "INSERT INTO beaver_lists (list_name, item_order, item_value) VALUES (?, ?, ?)",
                (self._name, new_order, self._serialize(value)),
            )

    def insert(self, index: int, value: T):
        """Inserts an item at a specific index."""
        with self._conn:
            list_len = len(self)
            if index <= 0:
                self.prepend(value)
                return
            if index >= list_len:
                self.push(value)
                return

            # Midpoint insertion for O(1) inserts
            order_before = self._get_order_at_index(index - 1)
            order_after = self._get_order_at_index(index)
            new_order = order_before + (order_after - order_before) / 2.0

            self._conn.execute(
                "INSERT INTO beaver_lists (list_name, item_order, item_value) VALUES (?, ?, ?)",
                (self._name, new_order, self._serialize(value)),
            )

    def pop(self) -> T | None:
        """Removes and returns the last item from the list."""
        with self._conn:
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT rowid, item_value FROM beaver_lists WHERE list_name = ? ORDER BY item_order DESC LIMIT 1",
                (self._name,),
            )
            result = cursor.fetchone()
            if not result:
                return None

            rowid_to_delete, value_to_return = result
            cursor.execute(
                "DELETE FROM beaver_lists WHERE rowid = ?", (rowid_to_delete,)
            )
            return self._deserialize(value_to_return)

    def deque(self) -> T | None:
        """Removes and returns the first item from the list."""
        with self._conn:
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT rowid, item_value FROM beaver_lists WHERE list_name = ? ORDER BY item_order ASC LIMIT 1",
                (self._name,),
            )
            result = cursor.fetchone()
            if not result:
                return None

            rowid_to_delete, value_to_return = result
            cursor.execute(
                "DELETE FROM beaver_lists WHERE rowid = ?", (rowid_to_delete,)
            )
            return self._deserialize(value_to_return)
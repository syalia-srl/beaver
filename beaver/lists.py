import json
import sqlite3
from typing import Any, Union


class ListWrapper:
    """A wrapper providing a Pythonic interface to a list in the database."""

    def __init__(self, name: str, conn: sqlite3.Connection):
        self._name = name
        self._conn = conn

    def __len__(self) -> int:
        """Returns the number of items in the list (e.g., `len(my_list)`)."""
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM beaver_lists WHERE list_name = ?", (self._name,)
        )
        count = cursor.fetchone()[0]
        cursor.close()
        return count

    def __getitem__(self, key: Union[int, slice]) -> Any:
        """
        Retrieves an item or slice from the list (e.g., `my_list[0]`, `my_list[1:3]`).
        """
        if isinstance(key, slice):
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
            results = [json.loads(row["item_value"]) for row in cursor.fetchall()]
            cursor.close()
            return results

        elif isinstance(key, int):
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
            return json.loads(result["item_value"]) if result else None

        else:
            raise TypeError("List indices must be integers or slices.")

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

    def push(self, value: Any):
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
                (self._name, new_order, json.dumps(value)),
            )

    def prepend(self, value: Any):
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
                (self._name, new_order, json.dumps(value)),
            )

    def insert(self, index: int, value: Any):
        """Inserts an item at a specific index."""
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

        with self._conn:
            self._conn.execute(
                "INSERT INTO beaver_lists (list_name, item_order, item_value) VALUES (?, ?, ?)",
                (self._name, new_order, json.dumps(value)),
            )

    def pop(self) -> Any:
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
            return json.loads(value_to_return)

    def deque(self) -> Any:
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
            return json.loads(value_to_return)

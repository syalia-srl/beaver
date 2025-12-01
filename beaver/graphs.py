import json
from typing import (
    Iterator,
    AsyncIterator,
    Protocol,
    runtime_checkable,
    TYPE_CHECKING,
    Tuple,
    Any,
)

from pydantic import BaseModel

from .manager import AsyncBeaverBase, atomic, emits
from .interfaces import Edge, IAsyncBeaverGraph

if TYPE_CHECKING:
    from .core import AsyncBeaverDB


class AsyncBeaverGraph[T: BaseModel](AsyncBeaverBase[T], IAsyncBeaverGraph[T]):
    """
    Manages directed relationships between entities.

    The generic type T refers to the type of the Edge Metadata.

    Table managed:
    - __beaver_edges__ (collection, source_item_id, target_item_id, label, metadata)
    """

    def __init__(self, name: str, db: "AsyncBeaverDB", model: type[T] | None = None):
        super().__init__(name, db, model)
        # Construct the concrete Edge model for this manager
        self._edge_model = Edge[model] if model else Edge

    @emits(
        "link",
        payload=lambda s, t, l, *args, **kwargs: dict(source=s, target=t, label=l),
    )
    @atomic
    async def link(
        self, source: str, target: str, label: str, metadata: T | None = None
    ):
        """Creates or updates a directed edge."""
        # Use the base manager's serializer to handle Pydantic models vs dicts
        # Default to empty dict if None (and no model enforced)
        meta_json = self._serialize(metadata) if metadata else None

        await self.connection.execute(
            """
            INSERT OR REPLACE INTO __beaver_edges__
            (collection, source_item_id, target_item_id, label, metadata)
            VALUES (?, ?, ?, ?, ?)
            """,
            (self._name, source, target, label, meta_json),
        )

    @emits(
        "unlink",
        payload=lambda s, t, l, *args, **kwargs: dict(source=s, target=t, label=l),
    )
    @atomic
    async def unlink(self, source: str, target: str, label: str):
        """Removes a directed edge."""
        await self.connection.execute(
            """
            DELETE FROM __beaver_edges__
            WHERE collection = ? AND source_item_id = ? AND target_item_id = ? AND label = ?
            """,
            (self._name, source, target, label),
        )

    async def linked(self, source: str, target: str, label: str) -> bool:
        """Checks if a specific edge exists."""
        cursor = await self.connection.execute(
            """
            SELECT 1 FROM __beaver_edges__
            WHERE collection = ? AND source_item_id = ? AND target_item_id = ? AND label = ?
            LIMIT 1
            """,
            (self._name, source, target, label),
        )
        return await cursor.fetchone() is not None

    async def get(self, source: str, target: str, label: str) -> Edge[T]:
        """
        Retrieves a specific edge with metadata.
        Raises KeyError if not found.
        """
        cursor = await self.connection.execute(
            """
            SELECT metadata FROM __beaver_edges__
            WHERE collection = ? AND source_item_id = ? AND target_item_id = ? AND label = ?
            """,
            (self._name, source, target, label),
        )
        row = await cursor.fetchone()

        if not row:
            raise KeyError(f"Edge not found: {source} -[{label}]-> {target}")

        # Deserialize using the base manager (handles T validation)
        meta_str = row["metadata"]
        meta_val = self._deserialize(meta_str)

        return self._edge_model(
            source=source, target=target, label=label, metadata=meta_val
        )

    async def children(
        self, source: str, label: str | None = None
    ) -> AsyncIterator[str]:
        """
        Yields target IDs connected by outgoing edges from 'source'.
        (Forward traversal: source -> target)
        """
        query = "SELECT target_item_id FROM __beaver_edges__ WHERE collection = ? AND source_item_id = ?"
        params = [self._name, source]

        if label:
            query += " AND label = ?"
            params.append(label)

        cursor = await self.connection.execute(query, tuple(params))
        async for row in cursor:
            yield row["target_item_id"]

    async def parents(
        self, target: str, label: str | None = None
    ) -> AsyncIterator[str]:
        """
        Yields source IDs connected by incoming edges to 'target'.
        (Reverse traversal: source -> target)
        """
        # This relies on the index (collection, target_item_id) for performance
        query = "SELECT source_item_id FROM __beaver_edges__ WHERE collection = ? AND target_item_id = ?"
        params = [self._name, target]

        if label:
            query += " AND label = ?"
            params.append(label)

        cursor = await self.connection.execute(query, tuple(params))
        async for row in cursor:
            yield row["source_item_id"]

    async def edges(
        self, source: str, label: str | None = None
    ) -> AsyncIterator[Edge[T]]:
        """
        Yields full Edge objects (including metadata) originating from 'source'.
        """
        query = "SELECT target_item_id, label, metadata FROM __beaver_edges__ WHERE collection = ? AND source_item_id = ?"
        params = [self._name, source]

        if label:
            query += " AND label = ?"
            params.append(label)

        cursor = await self.connection.execute(query, tuple(params))
        async for row in cursor:
            meta_str = row["metadata"]
            meta_val = self._deserialize(meta_str) if meta_str else None

            yield self._edge_model(
                source=source,
                target=row["target_item_id"],
                label=row["label"],
                metadata=meta_val,
            )

    async def count(self) -> int:
        cursor = await self.connection.execute(
            "SELECT COUNT(*) FROM __beaver_edges__ WHERE collection = ?", (self._name,)
        )
        return (await cursor.fetchone())[0]

    @atomic
    async def clear(self):
        await self.connection.execute(
            "DELETE FROM __beaver_edges__ WHERE collection = ?", (self._name,)
        )

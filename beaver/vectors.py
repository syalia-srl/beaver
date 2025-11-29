import json
import math
import struct
from typing import (
    List,
    Tuple,
    Iterator,
    AsyncIterator,
    Protocol,
    runtime_checkable,
    TYPE_CHECKING,
    Any,
)

from pydantic import BaseModel

from .manager import AsyncBeaverBase, atomic, emits

if TYPE_CHECKING:
    from .core import AsyncBeaverDB


class VectorItem[T](BaseModel):
    """Represents a stored vector with metadata."""

    id: str
    vector: List[float]
    metadata: T | None = None
    score: float = 0


@runtime_checkable
class IBeaverVectors[T](Protocol):
    """Protocol exposed to the user via BeaverBridge."""

    def set(self, id: str, vector: List[float], metadata: T | None = None) -> None: ...
    def get(self, id: str) -> VectorItem[T] | None: ...
    def delete(self, id: str) -> None: ...

    def search(self, vector: List[float], k: int = 10) -> List[VectorItem[T]]: ...

    def count(self) -> int: ...
    def clear(self) -> None: ...
    def __iter__(self) -> Iterator[VectorItem[T]]: ...


class AsyncBeaverVectors[T: BaseModel](AsyncBeaverBase[T]):
    """
    A simple, persistent vector store.

    Performs exact Nearest Neighbor search by doing a full scan
    and computing distances in memory.

    Table managed:
    - __beaver_vectors__ (collection, item_id, vector, metadata)
    """

    def __init__(self, name: str, db: "AsyncBeaverDB", model: type[T] | None = None):
        super().__init__(name, db, model)
        # T is the metadata model
        self._meta_model = model

    def _serialize_vector(self, vector: List[float]) -> bytes:
        """Packs a list of floats into binary data."""
        # Use 'f' for float (4 bytes) or 'd' for double (8 bytes).
        # 'f' is standard for most embeddings.
        return struct.pack(f"{len(vector)}f", *vector)

    def _deserialize_vector(self, data: bytes) -> List[float]:
        """Unpacks binary data into a list of floats."""
        count = len(data) // 4
        return list(struct.unpack(f"{count}f", data))

    def _cosine_similarity(self, v1: List[float], v2: List[float]) -> float:
        """Computes Cosine Similarity between two vectors."""
        if len(v1) != len(v2):
            return -1.0  # Dimension mismatch punishment

        dot_product = sum(a * b for a, b in zip(v1, v2))
        norm_v1 = math.sqrt(sum(a * a for a in v1))
        norm_v2 = math.sqrt(sum(b * b for b in v2))

        if norm_v1 == 0 or norm_v2 == 0:
            return 0.0

        return dot_product / (norm_v1 * norm_v2)

    @emits("set", payload=lambda id, *args, **kwargs: dict(id=id))
    @atomic
    async def set(self, id: str, vector: List[float], metadata: T | None = None):
        """
        Stores a vector and optional metadata.
        """
        vec_blob = self._serialize_vector(vector)

        # Serialize metadata using base manager logic
        meta_json = self._serialize(metadata) if metadata else None

        await self.connection.execute(
            """
            INSERT OR REPLACE INTO __beaver_vectors__
            (collection, item_id, vector, metadata)
            VALUES (?, ?, ?, ?)
            """,
            (self._name, id, vec_blob, meta_json),
        )

    @atomic
    async def get(self, id: str) -> VectorItem[T]:
        """Retrieves a vector item by ID."""
        cursor = await self.connection.execute(
            "SELECT vector, metadata FROM __beaver_vectors__ WHERE collection = ? AND item_id = ?",
            (self._name, id),
        )
        row = await cursor.fetchone()

        if not row:
            raise KeyError(id)

        vector = self._deserialize_vector(row["vector"])
        meta_val = self._deserialize(row["metadata"]) if row["metadata"] else None

        return VectorItem(id=id, vector=vector, metadata=meta_val)

    @emits("delete", payload=lambda id, *args, **kwargs: dict(id=id))
    @atomic
    async def delete(self, id: str):
        """Deletes a vector item."""
        await self.connection.execute(
            "DELETE FROM __beaver_vectors__ WHERE collection = ? AND item_id = ?",
            (self._name, id),
        )

    async def search(self, vector: List[float], k: int = 10) -> List[VectorItem[T]]:
        """
        Performs exact KNN search using Cosine Similarity.
        Scans the entire table for this collection.
        """
        query_vec = vector

        # 1. Fetch ALL vectors (Full Scan)
        # Optimization: We could stream this if memory is an issue,
        # but for a simple store, fetching all is fine.
        cursor = await self.connection.execute(
            "SELECT item_id, vector, metadata FROM __beaver_vectors__ WHERE collection = ?",
            (self._name,),
        )

        candidates = []
        async for row in cursor:
            # CPU Bound work inside the loop
            row_vec = self._deserialize_vector(row["vector"])
            score = self._cosine_similarity(query_vec, row_vec)

            candidates.append((score, row))

        # 2. Sort by Score Descending
        candidates.sort(key=lambda x: x[0], reverse=True)

        # 3. Take Top K and Hydrate
        top_k = candidates[:k]
        results = []

        for score, row in top_k:
            # Reconstruct item
            vec = self._deserialize_vector(row["vector"])
            meta_val = self._deserialize(row["metadata"]) if row["metadata"] else None

            item = VectorItem(
                id=row["item_id"], vector=vec, metadata=meta_val, score=score
            )
            results.append(item)

        return results

    async def count(self) -> int:
        cursor = await self.connection.execute(
            "SELECT COUNT(*) FROM __beaver_vectors__ WHERE collection = ?",
            (self._name,),
        )
        result = await cursor.fetchone()
        return result[0] if result else 0

    @atomic
    async def clear(self):
        await self.connection.execute(
            "DELETE FROM __beaver_vectors__ WHERE collection = ?", (self._name,)
        )

    async def __aiter__(self):
        cursor = await self.connection.execute(
            "SELECT item_id, vector, metadata FROM __beaver_vectors__ WHERE collection = ?",
            (self._name,),
        )
        async for row in cursor:
            vec = self._deserialize_vector(row["vector"])
            meta = self._deserialize(row["metadata"]) if row["metadata"] else None
            yield VectorItem(id=row["item_id"], vector=vec, metadata=meta)

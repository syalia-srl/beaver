# beaver/vectors.py

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
# Import Filter for type hinting (handling circular imports if necessary)
if TYPE_CHECKING:
    from .core import AsyncBeaverDB
    from .queries import Filter

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

    # Upgraded Search Signature
    def search(
        self,
        vector: List[float],
        k: int = 10,
        candidate_ids: List[str] | None = None,
        filters: List["Filter"] | None = None
    ) -> List[VectorItem[T]]: ...

    def count(self) -> int: ...
    def clear(self) -> None: ...
    def __iter__(self) -> Iterator[VectorItem[T]]: ...


class AsyncBeaverVectors[T: BaseModel](AsyncBeaverBase[T]):
    """
    A persistent vector store with metadata filtering support.

    Performs exact Nearest Neighbor search by:
    1. Filtering candidates via SQL (IDs + Metadata)
    2. Computing Cosine Similarity in memory on the survivors
    """

    def __init__(self, name: str, db: "AsyncBeaverDB", model: type[T] | None = None):
        super().__init__(name, db, model)
        self._meta_model = model

    def _serialize_vector(self, vector: List[float]) -> bytes:
        return struct.pack(f"{len(vector)}f", *vector)

    def _deserialize_vector(self, data: bytes) -> List[float]:
        count = len(data) // 4
        return list(struct.unpack(f"{count}f", data))

    def _cosine_similarity(self, v1: List[float], v2: List[float]) -> float:
        if len(v1) != len(v2):
            return -1.0

        dot_product = sum(a * b for a, b in zip(v1, v2))
        norm_v1 = math.sqrt(sum(a * a for a in v1))
        norm_v2 = math.sqrt(sum(b * b for b in v2))

        if norm_v1 == 0 or norm_v2 == 0:
            return 0.0

        return dot_product / (norm_v1 * norm_v2)

    @emits("set", payload=lambda id, *args, **kwargs: dict(id=id))
    @atomic
    async def set(self, id: str, vector: List[float], metadata: T | None = None):
        vec_blob = self._serialize_vector(vector)
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
        await self.connection.execute(
            "DELETE FROM __beaver_vectors__ WHERE collection = ? AND item_id = ?",
            (self._name, id),
        )

    async def search(
        self,
        vector: List[float],
        k: int = 10,
        candidate_ids: List[str] | None = None,
        filters: List["Filter"] | None = None
    ) -> List[VectorItem[T]]:
        """
        Performs vector search with optional pre-filtering.

        Args:
            vector: The query embedding.
            k: Number of nearest neighbors to return.
            candidate_ids: Optional list of IDs to restrict search to (Whitelist).
            filters: Optional list of metadata filters.
        """
        query_vec = vector

        # --- Build Dynamic SQL Query ---

        # Base query
        sql_parts = [
            "SELECT item_id, vector, metadata FROM __beaver_vectors__ WHERE collection = ?"
        ]
        params = [self._name]

        # 1. ID Filter (Whitelist)
        if candidate_ids is not None:
            if not candidate_ids:
                return [] # Whitelist provided but empty -> No results possible

            placeholders = ",".join("?" * len(candidate_ids))
            sql_parts.append(f"AND item_id IN ({placeholders})")
            params.extend(candidate_ids)

        # 2. Metadata Filters (JSON Extraction)
        # Note: This relies on SQLite's JSON extension (enabled by default in most Pythons)
        if filters:
            for f in filters:
                # We extract the field from the 'metadata' column
                # Syntax: json_extract(metadata, '$.fieldname')
                sql_parts.append(
                    f"AND json_extract(metadata, '$.{f.path}') {f.operator} ?"
                )
                params.append(f.value)

        # Execute
        full_sql = " ".join(sql_parts)
        cursor = await self.connection.execute(full_sql, tuple(params))

        # --- Scan & Score ---

        candidates = []
        async for row in cursor:
            # CPU Bound: Deserialize and Compute Dot Product
            # This loop is now smaller thanks to the SQL filtering above
            row_vec = self._deserialize_vector(row["vector"])
            score = self._cosine_similarity(query_vec, row_vec)

            candidates.append((score, row))

        # Sort by Score Descending
        candidates.sort(key=lambda x: x[0], reverse=True)

        # Hydrate Top K
        results = []
        for score, row in candidates[:k]:
            vec = self._deserialize_vector(row["vector"])
            meta_val = self._deserialize(row["metadata"]) if row["metadata"] else None

            results.append(
                VectorItem(
                    id=row["item_id"], vector=vec, metadata=meta_val, score=score
                )
            )

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

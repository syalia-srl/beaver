import json
import math
import struct
import numpy as np
from typing import (
    List,
    Iterator,
    Protocol,
    runtime_checkable,
    TYPE_CHECKING,
    Literal,
    Callable,
    Union,
    Optional,
)

from pydantic import BaseModel

from .manager import AsyncBeaverBase, atomic, emits

if TYPE_CHECKING:
    from .core import AsyncBeaverDB
    from .queries import Filter


class VectorItem[T](BaseModel):
    """Represents a stored vector with metadata."""

    id: str
    vector: List[float]
    metadata: T | None = None
    score: float = 0

    class Config:
        arbitrary_types_allowed = True


# Type Alias for Custom Metrics
# Accepts: (Matrix[N, D], Vector[D]) -> Scores[N]
Metric = Callable[[np.ndarray, np.ndarray], np.ndarray]


@runtime_checkable
class IBeaverVectors[T](Protocol):
    """Protocol exposed to the user via BeaverBridge."""

    def set(self, id: str, vector: List[float], metadata: T | None = None) -> None: ...
    def get(self, id: str) -> VectorItem[T] | None: ...
    def delete(self, id: str) -> None: ...

    def near(
        self,
        vector: List[float],
        k: int = 10,
        candidate_ids: List[str] | None = None,
        filters: List["Filter"] | None = None,
        metric: Optional[Metric] = None,
    ) -> List[VectorItem[T]]: ...

    def count(self) -> int: ...
    def clear(self) -> None: ...
    def __iter__(self) -> Iterator[VectorItem[T]]: ...


class AsyncBeaverVectors[T: BaseModel](AsyncBeaverBase[T]):
    """
    A persistent vector store accelerated by NumPy.

    Features:
    - NumPy Serialization for fast IO.
    - Pluggable Metric Strategies (Callable).
    - SQL-Pushdown for filtering.
    """

    def __init__(self, name: str, db: "AsyncBeaverDB", model: type[T] | None = None):
        super().__init__(name, db, model)
        self._meta_model = model

    def _serialize_vector(self, vector: List[float] | np.ndarray) -> bytes:
        """Converts a list/array to a raw float32 byte buffer."""
        if not isinstance(vector, np.ndarray):
            vector = np.array(vector, dtype=np.float32)
        return vector.tobytes()

    def _deserialize_vector(self, data: bytes) -> np.ndarray:
        """Zero-copy view of the byte buffer as a float32 array."""
        return np.frombuffer(data, dtype=np.float32)

    # --- Core API ---

    @emits("set", payload=lambda id, *args, **kwargs: dict(id=id))
    @atomic
    async def set(self, id: str, vector: List[float], metadata: T | None = None):
        """Stores a vector using NumPy serialization."""
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

        vec_np = self._deserialize_vector(row["vector"])
        vector = vec_np.tolist()
        meta_val = self._deserialize(row["metadata"]) if row["metadata"] else None

        return VectorItem(id=id, vector=vector, metadata=meta_val)

    @emits("delete", payload=lambda id, *args, **kwargs: dict(id=id))
    @atomic
    async def delete(self, id: str):
        await self.connection.execute(
            "DELETE FROM __beaver_vectors__ WHERE collection = ? AND item_id = ?",
            (self._name, id),
        )

    async def near(
        self,
        vector: List[float],
        k: int = 10,
        candidate_ids: List[str] | None = None,
        filters: List["Filter"] | None = None,
        metric: Optional[Metric] = None,
    ) -> List[VectorItem[T]]:
        """
        Performs vectorized search using the specified metric strategy.

        Args:
            vector: Query vector.
            k: Number of results.
            candidate_ids: Whitelist of IDs to search.
            filters: Metadata filters to apply via SQL.
            metric: Callable strategy (default: cosine).
                    Must return scores where LOWER is BETTER.
        """
        query_vec = np.array(vector, dtype=np.float32)

        # 1. Dynamic SQL Filtering
        sql_parts = [
            "SELECT item_id, vector, metadata FROM __beaver_vectors__ WHERE collection = ?"
        ]
        params = [self._name]

        if candidate_ids is not None:
            if not candidate_ids:
                return []
            placeholders = ",".join("?" * len(candidate_ids))
            sql_parts.append(f"AND item_id IN ({placeholders})")
            params.extend(candidate_ids)

        if filters:
            for f in filters:
                sql_parts.append(
                    f"AND json_extract(metadata, '$.{f.path}') {f.operator} ?"
                )
                params.append(f.value)

        full_sql = " ".join(sql_parts)
        cursor = await self.connection.execute(full_sql, tuple(params))
        rows = await cursor.fetchall()

        if not rows:
            return []

        # 2. Matrix Construction (Zero-Copy View)
        ids = []
        vectors_list = []
        metadatas = []

        for row in rows:
            ids.append(row["item_id"])
            vectors_list.append(self._deserialize_vector(row["vector"]))
            metadatas.append(row["metadata"])

        matrix = np.stack(vectors_list)

        # 3. Metric Calculation
        # Default to Cosine if not provided
        scoring_fn = metric if metric is not None else cosine

        # Compute scores (Assumption: Lower is Better)
        scores = scoring_fn(matrix, query_vec)

        # 4. Sort and Format
        # np.argsort sorts Ascending (Lowest -> Highest)
        # Since we enforced "Minimizing" semantics, we just take the first K.
        top_indices = np.argsort(scores)[:k]

        results = []
        for idx in top_indices:
            score = float(scores[idx])
            item_id = ids[idx]

            meta_str = metadatas[idx]
            meta_val = self._deserialize(meta_str) if meta_str else None
            vec_list = vectors_list[idx].tolist()

            results.append(
                VectorItem(
                    id=item_id,
                    vector=vec_list,
                    metadata=meta_val,
                    score=score,
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
            vec_np = self._deserialize_vector(row["vector"])
            meta = self._deserialize(row["metadata"]) if row["metadata"] else None
            yield VectorItem(id=row["item_id"], vector=vec_np.tolist(), metadata=meta)


# --- Public Metric Strategies ---


def cosine(matrix: np.ndarray, vector: np.ndarray) -> np.ndarray:
    """
    Computes Negative Cosine Similarity.
    Formula: (-1 * (A . B) / (||A|| * ||B||) + 1) / 2

    Returns values in range [0.0, 1.0].
    0.0 = Identical (Perfect Match)
    0.5 = Orthogonal
    1.0 = Opposite
    """
    dot_products = matrix.dot(vector)
    matrix_norms = np.linalg.norm(matrix, axis=1)
    query_norm = np.linalg.norm(vector)

    epsilon = 1e-10
    similarity = dot_products / ((matrix_norms * query_norm) + epsilon)

    # Negate so that lower is better (Minimizing)
    return -(similarity - 1) / 2  # Normalize to [0, 1] range


def euclid(matrix: np.ndarray, vector: np.ndarray) -> np.ndarray:
    """
    Computes Euclidean Distance.
    """
    # axis=1 calculates the norm for each row vector in the difference matrix
    return np.linalg.norm(matrix - vector, axis=1)


def manhattan(matrix: np.ndarray, vector: np.ndarray) -> np.ndarray:
    """
    Computes Manhattan Distance.
    """
    return np.sum(np.abs(matrix - vector), axis=1)

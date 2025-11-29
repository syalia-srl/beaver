import json
import numpy as np
from typing import (
    List,
    Iterator,
    Protocol,
    runtime_checkable,
    TYPE_CHECKING,
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

    # Allow arbitrary types for numpy compatibility if needed,
    # though we usually convert back to list for Pydantic


@runtime_checkable
class IBeaverVectors[T](Protocol):
    """Protocol exposed to the user via BeaverBridge."""

    def set(self, id: str, vector: List[float], metadata: T | None = None) -> None: ...
    def get(self, id: str) -> VectorItem[T] | None: ...
    def delete(self, id: str) -> None: ...

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
    A persistent vector store accelerated by NumPy.

    Features:
    - NumPy Serialization for fast IO.
    - Vectorized Cosine Similarity (Matrix Multiplication).
    - SQL-Pushdown for filtering before matrix construction.
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

        # Convert numpy array back to list for user consumption/Pydantic
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

    async def search(
        self,
        vector: List[float],
        k: int = 10,
        candidate_ids: List[str] | None = None,
        filters: List["Filter"] | None = None
    ) -> List[VectorItem[T]]:
        """
        Performs vectorized KNN search.

        1. Filters candidates using SQL (ID whitelist + Metadata filters).
        2. Loads surviving binary blobs into a NumPy Matrix.
        3. Computes Cosine Similarity via Matrix Multiplication.
        """
        # Ensure query is a numpy array
        query_vec = np.array(vector, dtype=np.float32)

        # --- 1. Dynamic SQL Building (Filtering) ---

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
                # Requires SQLite JSON1 extension (standard in Python 3.9+)
                sql_parts.append(
                    f"AND json_extract(metadata, '$.{f.path}') {f.operator} ?"
                )
                params.append(f.value)

        full_sql = " ".join(sql_parts)
        cursor = await self.connection.execute(full_sql, tuple(params))
        rows = await cursor.fetchall()

        if not rows:
            return []

        # --- 2. Matrix Construction (IO Bound) ---

        ids = []
        vectors_list = []
        metadatas = []

        for row in rows:
            ids.append(row["item_id"])
            # Zero-copy view from bytes
            vectors_list.append(self._deserialize_vector(row["vector"]))
            metadatas.append(row["metadata"])

        # Stack into (N, D) matrix
        matrix = np.stack(vectors_list)

        # --- 3. Vectorized Math (CPU Bound) ---

        # Cosine Similarity: (A . B) / (||A|| * ||B||)

        # Dot product of Matrix (N, D) with Query (D,) -> (N,)
        dot_products = matrix.dot(query_vec)

        # Compute Norms
        # axis=1 calculates norm for each row vector
        matrix_norms = np.linalg.norm(matrix, axis=1)
        query_norm = np.linalg.norm(query_vec)

        # Avoid division by zero
        epsilon = 1e-10
        scores = dot_products / ((matrix_norms * query_norm) + epsilon)

        # --- 4. Sorting & Formatting ---

        # argsort gives indices of sorted elements (ascending)
        # We take the last k elements (highest scores) and reverse them
        top_indices = np.argsort(scores)[-k:][::-1]

        results = []
        for idx in top_indices:
            score = float(scores[idx]) # Convert np.float32 to python float
            item_id = ids[idx]

            # Retrieve cached metadata string
            meta_str = metadatas[idx]
            meta_val = self._deserialize(meta_str) if meta_str else None

            # Convert vector back to list for the model
            vec_list = vectors_list[idx].tolist()

            results.append(
                VectorItem(
                    id=item_id,
                    vector=vec_list,
                    metadata=meta_val,
                    score=score
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
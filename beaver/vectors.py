import numpy as np
from typing import (
    List,
    TYPE_CHECKING,
    Literal,
    Callable,
    Optional,
)

from pydantic import BaseModel

from .manager import AsyncBeaverBase, atomic, emits
from .interfaces import IAsyncBeaverVectors, VectorItem
from .queries import Filter

if TYPE_CHECKING:
    from .core import AsyncBeaverDB


# Type Alias for Custom Metrics
# Accepts: (Matrix[N, D], Vector[D]) -> Scores[N]
type Metric = Callable[[np.ndarray, np.ndarray], np.ndarray]


class AsyncBeaverVectors[T: BaseModel](AsyncBeaverBase[T], IAsyncBeaverVectors[T]):
    """
    A persistent vector store with Hybrid Linear/LSH search.

    Features:
    - Hybrid Search: Automatically switches between Exact Scan and LSH.
    - SimHash LSH: Uses random projection (cosine) for O(1) lookups.
    - Zero-Dependency: Pure NumPy implementation.
    """

    def __init__(self, name: str, db: "AsyncBeaverDB", model: type[T] | None = None):
        super().__init__(name, db, model)
        self._meta_model = model
        self._hyperplanes: np.ndarray | None = None
        self._threshold_cache: int | None = None

    def _serialize_vector(self, vector: List[float] | np.ndarray) -> bytes:
        """Converts a list/array to a raw float32 byte buffer."""
        if not isinstance(vector, np.ndarray):
            vector = np.array(vector, dtype=np.float32)
        return vector.tobytes()

    def _deserialize_vector(self, data: bytes) -> np.ndarray:
        """Zero-copy view of the byte buffer as a float32 array."""
        return np.frombuffer(data, dtype=np.float32)

    async def _get_threshold(self) -> int:
        """
        Returns the threshold N where we switch from Linear to LSH.
        Default: 10,000 vectors.
        """
        if self._threshold_cache is None:
            # In future, this could read from a config table
            self._threshold_cache = 10_000
        return self._threshold_cache

    # --- LSH Internals ---

    async def _ensure_lsh_hyperplanes(self, dim: int, nbits: int = 16):
        """
        Loads or creates the random projection matrix (Hyperplanes).
        We use 16 bits to create ~65k buckets, optimal for <5M items.
        """
        if self._hyperplanes is not None:
            if self._hyperplanes.shape[1] != dim:
                raise ValueError(
                    f"Vector dimension mismatch. Index expects {self._hyperplanes.shape[1]}, got {dim}"
                )
            return

        # 1. Try to fetch from DB
        cursor = await self.connection.execute(
            "SELECT hyperplanes FROM __beaver_lsh_config__ WHERE collection = ?",
            (self._name,),
        )
        row = await cursor.fetchone()

        if row:
            self._hyperplanes = np.frombuffer(row["hyperplanes"], dtype=np.float32)
            # Reshape: (nbits, dim)
            self._hyperplanes = self._hyperplanes.reshape(nbits, -1)
            return

        # 2. Create new if missing (Orthogonal Initialization)
        # Orthogonal planes cover the sphere more evenly than random Gaussian
        H = np.random.randn(dim, nbits)
        Q, _ = np.linalg.qr(H)
        hyperplanes = Q.T.astype(np.float32)  # (nbits, dim)

        await self.connection.execute(
            "INSERT INTO __beaver_lsh_config__ (collection, hyperplanes) VALUES (?, ?)",
            (self._name, hyperplanes.tobytes()),
        )
        self._hyperplanes = hyperplanes

    def _hash_vector(self, vector: np.ndarray) -> int:
        """
        Projects vector to a single integer bucket using SimHash (Sign Random Projection).
        Implicitly normalizes vector to project onto unit sphere (Cosine).
        """
        # 1. Normalize (L2 Norm)
        norm = np.linalg.norm(vector)
        if norm > 1e-10:
            v_norm = vector / norm
        else:
            v_norm = vector  # Zero vector stays zero

        # 2. Project (Dot Product)
        # (nbits, dim) @ (dim,) -> (nbits,)
        projections = self._hyperplanes @ v_norm

        # 3. Sign -> Bitmask -> Int
        bits = (projections > 0).astype(int)

        # Fast conversion to int using bit shifting
        hash_val = 0
        for bit in bits:
            hash_val = (hash_val << 1) | bit

        return hash_val

    # --- Core API ---

    @emits("set", payload=lambda id, *args, **kwargs: dict(id=id))
    @atomic
    async def set(self, id: str, vector: List[float], metadata: T | None = None):
        """
        Stores a vector and updates its LSH index entry.
        """
        vec_np = np.array(vector, dtype=np.float32)

        # 1. Ensure LSH config exists
        await self._ensure_lsh_hyperplanes(vec_np.shape[0])

        # 2. Calculate Hash
        bucket_id = self._hash_vector(vec_np)

        # 3. Serialize Data
        vec_blob = self._serialize_vector(vec_np)
        meta_json = self._serialize(metadata) if metadata else None

        # 4. Write to Main Store
        await self.connection.execute(
            """
            INSERT OR REPLACE INTO __beaver_vectors__
            (collection, item_id, vector, metadata)
            VALUES (?, ?, ?, ?)
            """,
            (self._name, id, vec_blob, meta_json),
        )

        # 5. Write to LSH Index
        await self.connection.execute(
            """
            INSERT OR REPLACE INTO __beaver_lsh_index__
            (collection, bucket_id, item_id)
            VALUES (?, ?, ?)
            """,
            (self._name, bucket_id, id),
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
        # Atomic Delete from both tables
        await self.connection.execute(
            "DELETE FROM __beaver_vectors__ WHERE collection = ? AND item_id = ?",
            (self._name, id),
        )
        await self.connection.execute(
            "DELETE FROM __beaver_lsh_index__ WHERE collection = ? AND item_id = ?",
            (self._name, id),
        )

    async def near(
        self,
        vector: List[float],
        k: int = 10,
        candidate_ids: List[str] | None = None,
        filters: List["Filter"] | None = None,
        metric: Optional[Metric] = None,
        method: Literal["auto", "exact", "lsh"] = "auto",
    ) -> List[VectorItem[T]]:
        """
        Performs vectorized search.

        Args:
            vector: Query vector.
            k: Number of results.
            candidate_ids: Whitelist of IDs to search.
            filters: Metadata filters.
            metric: Custom scoring function (default: cosine).
            method: 'auto' (default), 'exact' (linear scan), or 'lsh' (index).
        """
        query_np = np.array(vector, dtype=np.float32)

        # 1. Decide Strategy
        use_linear = False

        if method == "exact":
            use_linear = True
        elif method == "lsh":
            use_linear = False
        else:  # auto
            # Check threshold
            threshold = await self._get_threshold()
            count = await self.count()
            use_linear = count < threshold

        # 2. Execute
        if use_linear:
            return await self._linear_scan(
                query_np, k, candidate_ids, filters, metric, rows=None
            )
        else:
            return await self._lsh_search(query_np, k, candidate_ids, filters, metric)

    async def _linear_scan(
        self,
        query_np: np.ndarray,
        k: int,
        candidate_ids: List[str] | None = None,
        filters: List["Filter"] | None = None,
        metric: Optional[Metric] = None,
        rows: list | None = None,
    ) -> List[VectorItem[T]]:
        """
        Performs exact brute-force search (O(N)).
        If 'rows' is provided, it scans those specific rows (used by LSH refinement).
        """
        # 1. Fetch Data (if not provided)
        if rows is None:
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

        # 2. Matrix Construction (Zero-Copy)
        ids = []
        vectors_list = []
        metadatas = []

        for row in rows:
            ids.append(row["item_id"])
            vectors_list.append(self._deserialize_vector(row["vector"]))
            metadatas.append(row["metadata"])

        matrix = np.stack(vectors_list)

        # 3. Metric Calculation
        scoring_fn = metric if metric is not None else cosine
        scores = scoring_fn(matrix, query_np)

        # 4. Sort and Top-K
        # scores are "Lower is Better", so standard argsort works
        top_indices = np.argsort(scores)[:k]

        results = []
        for idx in top_indices:
            score = float(scores[idx])
            item_id = ids[idx]
            meta_str = metadatas[idx]
            meta_val = self._deserialize(meta_str) if meta_str else None
            vec_list = vectors_list[idx].tolist()

            results.append(
                VectorItem(id=item_id, vector=vec_list, metadata=meta_val, score=score)
            )

        return results

    async def _lsh_search(
        self,
        query_np: np.ndarray,
        k: int,
        candidate_ids: List[str] | None = None,
        filters: List["Filter"] | None = None,
        metric: Optional[Metric] = None,
    ) -> List[VectorItem[T]]:
        """
        Performs Approximate Nearest Neighbor search using SimHash.
        Strategy: Hamming Distance <= 1 (Checks 17 buckets).
        """
        # Ensure hyperplanes are loaded
        await self._ensure_lsh_hyperplanes(query_np.shape[0])

        # 1. Hash Query
        query_hash = self._hash_vector(query_np)

        # 2. Generate Candidates (Multi-Probe: Dist 0 and 1)
        buckets = {query_hash}
        nbits = self._hyperplanes.shape[0]

        for i in range(nbits):
            buckets.add(query_hash ^ (1 << i))

        bucket_list = list(buckets)
        placeholders = ",".join("?" * len(bucket_list))

        # 3. SQL Fetch (Pushdown candidates)
        # We join to filter by both Bucket (LSH) and Metadata/ID (User query)
        sql_parts = [
            """
            SELECT v.item_id, v.vector, v.metadata
            FROM __beaver_lsh_index__ idx
            JOIN __beaver_vectors__ v ON idx.item_id = v.item_id
            WHERE idx.collection = ?
            AND idx.bucket_id IN ({})
            """.format(
                placeholders
            )
        ]
        params = [self._name, *bucket_list]

        # Apply user filters to the JOINED table 'v'
        if candidate_ids is not None:
            if not candidate_ids:
                return []
            id_placeholders = ",".join("?" * len(candidate_ids))
            sql_parts.append(f"AND v.item_id IN ({id_placeholders})")
            params.extend(candidate_ids)

        if filters:
            for f in filters:
                sql_parts.append(
                    f"AND json_extract(v.metadata, '$.{f.path}') {f.operator} ?"
                )
                params.append(f.value)

        full_sql = " ".join(sql_parts)
        cursor = await self.connection.execute(full_sql, tuple(params))
        rows = await cursor.fetchall()

        # 4. Fallback Safety Net
        # If LSH returns nothing (rare boundary case), fall back to linear scan
        if not rows:
            return await self._linear_scan(
                query_np, k, candidate_ids, filters, metric, rows=None
            )

        # 5. Refine (Exact Re-ranking on candidate subset)
        return await self._linear_scan(
            query_np, k, candidate_ids, filters, metric, rows=rows
        )

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
        await self.connection.execute(
            "DELETE FROM __beaver_lsh_index__ WHERE collection = ?", (self._name,)
        )
        # Note: We generally keep the LSH config (hyperplanes) to ensure stable hashing
        # if the user adds new data later.

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

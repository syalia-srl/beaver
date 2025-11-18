---
number: 24
title: "Refactor VectorIndex to be a swappable strategy and add LSH implementation"
state: open
labels:
---

### 1. Concept

The current `NumpyVectorIndex` provides an excellent, zero-dependency default for vector search based on a linear scan. However, its `O(N+k)` search complexity can be a bottleneck for larger datasets.

This feature proposes refactoring the vector index into a "Strategy Pattern":
1.  **Define a `VectorIndex` Protocol:** Create a formal interface that all vector index strategies must implement. Crucially, this interface must be **Async-Native** to work with the new core (Issue #25) and support **Batching** (Issue #26).
2.  **Refactor `NumpyVectorIndex`:** The current implementation will be retained as the default "linear" strategy but updated to be async.
3.  **Add `LSHVectorIndex`:** A new, swappable strategy will be implemented based on Locality-Sensitive Hashing (LSH). This will provide `O(k)` (approximate) search performance without adding heavy dependencies.
4.  **Add Factory Toggle:** Users will be able to select their desired strategy via a new `index_strategy` parameter in the `db.collection()` factory method.

### 2. Justification

* **Performance Flexibility:** LSH provides a well-understood trade-off, sacrificing perfect accuracy for a significant speedup on large datasets. This allows users to choose the right algorithm for their scale.
* **Extensibility:** Refactoring to a protocol-based design makes it trivial to add other `numpy`-based ANN strategies in the future (e.g., simple k-d trees) without modifying the `CollectionManager`.
* **Async Compatibility:** The new protocol ensures that vector operations (which require database I/O for logging and compaction) do not block the main event loop in the new Async-First architecture.

### 3. Proposed API

The only user-facing change will be a new optional parameter in the `BeaverDB.collection()` factory method:

```python
# In beaver/core.py

class BeaverDB:
    # ...
    def collection[D: Document](
        self,
        name: str,
        model: Type[D] | None = None,
        index_strategy: str = "linear"  # <-- New parameter
    ) -> CollectionManager[D]:
        """
        Returns a singleton CollectionManager...

        Args:
            ...
            index_strategy (str): The in-memory search algorithm to use.
                                  'linear' (default): Brute-force O(N) linear scan.
                                  'lsh': Approximate O(k) search via Locality-Sensitive Hashing.
        """
        return self.singleton(
            CollectionManager,
            name,
            model,
            index_strategy=index_strategy  # Pass to CollectionManager
        )
```

### 4. Implementation Design

#### A. The `VectorIndex` Protocol

We will create a new file (e.g., `beaver/vector_interface.py`) to define the formal protocol. All methods interacting with the database are `async`.

```python
from typing import Protocol, List, Tuple, Any

class VectorIndex(Protocol):
    def __init__(self, collection_name: str, db: Any): ...

    async def index(self, vector: list[float], item_id: str, cursor: Any):
        """Logs a single vector insertion."""
        ...

    async def index_many(self, items: list[tuple[list[float], str]], cursor: Any):
        """
        Logs multiple vector insertions efficiently.
        Required for supporting the .batched() API (Issue #26).
        """
        ...

    async def drop(self, item_id: str, cursor: Any):
        """Logs a vector deletion."""
        ...

    async def search(self, embedding: list[float], top_k: int) -> List[Tuple[str, float]]:
        """
        Performs the nearest neighbor search.
        Should ideally use asyncio.to_thread for heavy numpy calculations.
        """
        ...

    async def compact(self, cursor: Any):
        """Triggers a compaction/rebuild of the index."""
        ...
```

#### B. Refactor `NumpyVectorIndex`

The existing `NumpyVectorIndex` class will be refactored to formally implement this async protocol.

  * `index` / `drop`: Update to `async def` and `await cursor.execute`.
  * `index_many`: Implement using `await cursor.executemany` and batched in-memory updates.
  * `search`: Update to `async def`.

#### C. New `LSHVectorIndex` Implementation

A new class, `LSHVectorIndex`, will be created and will also implement the `VectorIndex` protocol.

  * **Internal State:** It will *not* use a delta index. It will maintain a single, unified in-memory state:

    1.  `hyperplanes: np.ndarray`: The random hyperplanes for hashing.
    2.  `buckets: dict[int, list[int]]`: A mapping of hash codes to *indices* in the main `_vector_matrix`.
    3.  `_vector_matrix: np.ndarray`: A single `O(N)` matrix of all vectors.
    4.  `_vector_ids: list[str]`: A list mapping matrix indices to document IDs.

  * **`_load_base_index()` (O(N) Rebuild):**

      * This is an `O(N)` operation that reads all vectors from `beaver_collections` via `aiosqlite` streaming.
      * It builds the `buckets` dictionary from scratch.

  * **`_sync_deltas()` (O(k) Sync):**

      * Reads the `k` new vectors from the log asynchronously.
      * Hashes new vectors and updates `buckets` and `_vector_matrix`.

  * **`search()` (O(k) Search):**

      * Hashes the query vector to get its bucket ID(s).
      * Retrieves the list of candidate indices from the `buckets` dict.
      * Performs an exact `numpy` linear scan *only* on the candidate vectors.

#### D. Factory Update in `CollectionManager`

The `CollectionManager` will be updated to act as the factory that selects the strategy.

```python
# In beaver/collections.py
from .vector_strategies.linear import NumpyVectorIndex
from .vector_strategies.lsh import LSHVectorIndex

class CollectionManager[B: BaseModel](ManagerBase[B]):
    def __init__(self, ..., index_strategy: str = "linear"):
        # ...
        if index_strategy == "lsh":
            self._vector_index = LSHVectorIndex(name, db)
        elif index_strategy == "linear":
            self._vector_index = NumpyVectorIndex(name, db)
        # ...
```

### 5. High-Level Roadmap

1.  Create `beaver/vector_interface.py` with the async `VectorIndex` protocol.
2.  Refactor `beaver/vectors.py` to make `NumpyVectorIndex` async and add `index_many`.
3.  Implement `LSHVectorIndex`, ensuring it uses `await` for all DB interactions.
4.  Update `CollectionManager` to use the new async vector methods and the strategy factory.
5.  Add unit tests for LSH and async behavior.
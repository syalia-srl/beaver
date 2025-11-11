---
number: 24
title: "Refactor VectorIndex to be a swappable strategy and add LSH implementation"
state: open
labels:
---

### 1. Concept

The current `NumpyVectorIndex` provides an excellent, zero-dependency default for vector search based on a linear scan. However, its `O(N+k)` search complexity can be a bottleneck for larger datasets.

This feature proposes refactoring the vector index into a "Strategy Pattern":
1.  **Define a `VectorIndex` Protocol:** Create a formal interface that all vector index strategies must implement.
2.  **Refactor `NumpyVectorIndex`:** The current implementation will be retained as the default "linear" strategy.
3.  **Add `LSHVectorIndex`:** A new, swappable strategy will be implemented based on Locality-Sensitive Hashing (LSH). This will provide `O(k)` (approximate) search performance without adding heavy dependencies.
4.  **Add Factory Toggle:** Users will be able to select their desired strategy via a new `index_strategy` parameter in the `db.collection()` factory method.

### 2. Justification

* **Performance Flexibility:** LSH provides a well-understood trade-off, sacrificing perfect accuracy for a significant speedup on large datasets. This allows users to choose the right algorithm for their scale.
* **Extensibility:** Refactoring to a protocol-based design makes it trivial to add other `numpy`-based ANN strategies in the future (e.g., simple k-d trees) without modifying the `CollectionManager`.
* **Aligns with Philosophy:** This keeps the "Simplicity" and "Minimal Dependency" principles by defaulting to the simple linear scan, while allowing users to *opt-in* to a more complex, performant strategy.

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

We will create a new file (e.g., `beaver/vector_interface.py`) to define the formal protocol. As discussed, this protocol **will not** include `delta_size`, as that is an implementation detail of the linear index.

```python
class VectorIndex(Protocol):
    def __init__(self, collection_name: str, db: IDatabase): ...

    def index(self, vector: list[float], item_id: str, cursor: sqlite3.Cursor):
        """Logs a vector insertion."""
        ...

    def drop(self, item_id: str, cursor: sqlite3.Cursor):
        """Logs a vector deletion."""
        ...

    def search(self, embedding: list[float], top_k: int) -> List[Tuple[str, float]]:
        """Performs the nearest neighbor search."""
        ...

    def compact(self, cursor: sqlite3.Cursor):
        """Triggers a compaction/rebuild of the index."""
        ...
```

#### B. Refactor `NumpyVectorIndex`

The existing `NumpyVectorIndex` class will be refactored to formally implement this protocol, but its internal logic (using `_n_matrix`, `_k_matrix`, `_deleted_ids`, and `delta_size`) will remain unchanged.

#### C. New `LSHVectorIndex` Implementation

A new class, `LSHVectorIndex`, will be created and will also implement the `VectorIndex` protocol.

  * **Internal State:** It will *not* use a delta index. It will maintain a single, unified in-memory state:

    1.  `hyperplanes: np.ndarray`: The random hyperplanes for hashing.
    2.  `buckets: dict[int, list[int]]`: A mapping of hash codes to *indices* in the main `_vector_matrix`.
    3.  `_vector_matrix: np.ndarray`: A single `O(N)` matrix of all vectors.
    4.  `_vector_ids: list[str]`: A list mapping matrix indices to document IDs.
    5.  It will still use `_check_and_sync`, `_load_base_index`, and `_sync_deltas` to read from the `beaver_vector_change_log`.

  * **`_load_base_index()` (O(N) Rebuild):**

      * This is an `O(N)` operation that reads all vectors from `beaver_collections` into `_vector_matrix` and `_vector_ids`.
      * It then iterates over `_vector_matrix`, hashes every vector, and builds the `buckets` dictionary from scratch.

  * **`_sync_deltas()` (O(k) Sync):**

      * Reads the `k` new vectors from the log.
      * For each new vector, appends it to `_vector_matrix` and its ID to `_vector_ids`.
      * It then hashes the new vector and appends its new index to the appropriate list in the `buckets` dictionary.

  * **`search()` (O(k) Search):**

      * Hashes the query vector to get its bucket ID(s).
      * Retrieves the list of candidate indices from the `buckets` dict.
      * Performs an exact `numpy` linear scan *only* on the candidate vectors.

  * **`compact()`:**

      * This is *not* a no-op. When `CollectionManager` triggers a compaction (to clear the log), this method *must* dump its in-memory state and call `_load_base_index()` to perform a full `O(N)` rebuild from the `beaver_collections` table, just like `NumpyVectorIndex`.

#### D. Factory Update in `CollectionManager`

The `CollectionManager` will be updated to act as the factory that selects the strategy.

```python
# In beaver/collections.py
from .vector_strategies.linear import NumpyVectorIndex
from .vector_strategies.lsh import LSHVectorIndex
from .vector_interface import VectorIndex

class CollectionManager[B: BaseModel](ManagerBase[B]):

    def __init__(
        self,
        name: str,
        db: IDatabase,
        model: Type[B] | None = None,
        index_strategy: str = "linear"  # <-- Accept arg
    ):
        super().__init__(name, db, model)

        # "Strategy" pattern
        if index_strategy == "lsh":
            self._vector_index: VectorIndex = LSHVectorIndex(name, db)
        elif index_strategy == "linear":
            self._vector_index: VectorIndex = NumpyVectorIndex(name, db)
        else:
            raise ValueError(f"Unknown index_strategy: '{index_strategy}'")

        # ... rest of init ...
```

### 5. High-Level Roadmap

1.  Create the `VectorIndex` protocol in a new `beaver/vector_interface.py` file (or similar).
2.  Refactor `beaver/vectors.py` so `NumpyVectorIndex` formally implements the new protocol.
3.  Implement the new `LSHVectorIndex` class, ensuring it uses the same log-based sync mechanism (`_check_and_sync`, etc.).
4.  Update `BeaverDB.collection()` in `beaver/core.py` to accept the `index_strategy` parameter.
5.  Update `CollectionManager.__init__` in `beaver/collections.py` to act as the factory for selecting the correct vector index strategy.
6.  Add unit tests for the LSH implementation and integration tests to verify the `index_strategy` toggle works.
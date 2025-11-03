import sqlite3
import threading
import time
import random
from typing import List, Tuple, Set, Dict, Optional

from .types import IDatabase
from .locks import LockManager

import numpy as np

# --- Constants for change log ---
INSERT_OPERATION = 1
DELETE_OPERATION = 2


class NumpyVectorIndex:
    """
    Manages a persistent, multi-process-safe vector index using numpy for
    linear search.

    This class uses a log-based delta-sync mechanism to keep multiple processes
    up-to-date with minimal overhead, performing O(N) search and O(k) sync performance.
    """

    def __init__(self, collection_name: str, db: IDatabase):
        """
        Initializes the NumpyVectorIndex for a specific collection.
        """
        self._collection = collection_name
        self._db = db

        # A lock to ensure thread safety for in-memory operations and synchronization checks.
        self._thread_lock = threading.Lock()

        # --- In-Memory State ---
        # The dimension of the vectors in this collection.
        self._dimension: int | None = None

        # Base Index (Compacted, O(N))
        self._n_matrix: np.ndarray | None = None
        self._n_ids: List[str] = []

        # Delta Index (In-memory, O(k))
        self._k_matrix: np.ndarray | None = None
        self._k_ids: List[str] = []

        # Tombstones for deleted IDs
        self._deleted_ids: Set[str] = set()

        # State tracking
        self._local_base_version: int = -1
        self._last_seen_log_id: int = -1
        self._is_initialized: bool = False

    @property
    def base_size(self) -> int:
        """Returns the number of vectors in the base (compacted) index."""
        with self._thread_lock:
            return len(self._n_ids)

    @property
    def delta_size(self) -> int:
        """Returns the number of vectors in the delta (in-memory) index."""
        with self._thread_lock:
            return len(self._k_ids)

    def index(self, vector: np.ndarray, item_id: str, cursor: sqlite3.Cursor):
        """
        Logs a vector insertion and updates the current process's in-memory
        delta index immediately.

        This must be called inside a transaction managed by CollectionManager.
        """
        # 1. Log the insertion to the database
        cursor.execute(
            "INSERT INTO _vector_change_log (collection_name, item_id, operation_type) VALUES (?, ?, ?)",
            (self._collection, item_id, INSERT_OPERATION)
        )
        new_log_id = cursor.lastrowid

        # 2. Call the fast-path helper to update this process's in-memory state
        if new_log_id:
            self._fast_path_insert(vector, item_id, new_log_id)

    def drop(self, item_id: str, cursor: sqlite3.Cursor):
        """
        Logs a vector deletion and updates the current process's in-memory
        tombstones immediately.

        This must be called inside a transaction managed by CollectionManager.
        """
        # 1. Log the deletion to the database
        cursor.execute(
            "INSERT INTO _vector_change_log (collection_name, item_id, operation_type) VALUES (?, ?, ?)",
            (self._collection, item_id, DELETE_OPERATION)
        )
        new_log_id = cursor.lastrowid

        # 2. Call the fast-path helper to update this process's in-memory state
        if new_log_id:
            self._fast_path_delete(item_id, new_log_id)

    def _infer_and_validate_dimension(self, vector: np.ndarray):
        """
        Infers the vector dimension from the first operation and validates
        subsequent vectors against it.
        """
        dim = vector.shape[-1]
        with self._thread_lock:
            if self._dimension is None:
                self._dimension = dim
            elif self._dimension != dim:
                raise ValueError(
                    f"Vector dimension mismatch for collection '{self._collection}'. "
                    f"Expected {self._dimension}, but got {dim}."
                )

    def _get_db_versions(self, cursor: sqlite3.Cursor) -> Tuple[int, int]:
        """Gets the current base_version and max_log_id from the database."""
        cursor.execute(
            "SELECT base_version FROM beaver_collection_versions WHERE collection_name = ?",
            (self._collection,),
        )
        result = cursor.fetchone()
        db_base_version = result[0] if result else 0

        cursor.execute(
            "SELECT MAX(log_id) FROM _vector_change_log WHERE collection_name = ?",
            (self._collection,)
        )
        result = cursor.fetchone()
        db_max_log_id = result[0] if result and result[0] is not None else 0

        return db_base_version, db_max_log_id

    def _load_base_index(self, cursor: sqlite3.Cursor, db_base_version: int, db_max_log_id: int):
        """
        Loads all data from the main tables, rebuilding the in-memory index
        from scratch. This is the "pay the cost" moment for startup and
        post-compaction.
        """
        # Fetch all non-deleted vectors
        cursor.execute(
            """
            SELECT c.item_id, c.item_vector
            FROM beaver_collections c
            LEFT JOIN _vector_change_log l ON c.collection = l.collection_name AND c.item_id = l.item_id AND l.operation_type = ?
            WHERE c.collection = ? AND c.item_vector IS NOT NULL
            GROUP BY c.item_id
            HAVING MAX(CASE WHEN l.operation_type = ? THEN l.log_id ELSE 0 END) = 0
            """,
            (DELETE_OPERATION, self._collection, DELETE_OPERATION)
        )

        base_vectors = []
        base_ids = []
        for row in cursor.fetchall():
            vector = np.frombuffer(row["item_vector"], dtype=np.float32)
            self._infer_and_validate_dimension(vector)
            base_vectors.append(vector)
            base_ids.append(row["item_id"])

        if base_vectors:
            assert isinstance(self._dimension, int)
            self._n_matrix = np.array(base_vectors).reshape(-1, self._dimension)
            self._n_ids = base_ids
        else:
            self._n_matrix = None
            self._n_ids = []

        # Base index is now loaded, so delta index and tombstones are empty
        self._k_matrix = None
        self._k_ids = []
        self._deleted_ids = set()

        # Update state
        self._local_base_version = db_base_version
        self._last_seen_log_id = db_max_log_id
        self._is_initialized = True

    def _sync_deltas(self, cursor: sqlite3.Cursor, db_max_log_id: int):
        """
        Applies only the new changes from the log table since the last sync.
        """
        cursor.execute(
            """
            SELECT l.log_id, l.item_id, l.operation_type, c.item_vector
            FROM _vector_change_log l
            LEFT JOIN beaver_collections c ON l.collection_name = c.collection AND l.item_id = c.item_id
            WHERE l.collection_name = ? AND l.log_id > ?
            ORDER BY l.log_id ASC
            """,
            (self._collection, self._last_seen_log_id)
        )

        rows = cursor.fetchall()
        if not rows:
            return  # No changes

        new_k_vectors = list(self._k_matrix) if self._k_matrix is not None else []
        new_k_ids = list(self._k_ids)

        for row in rows:
            item_id = row["item_id"]
            op_type = row["operation_type"]

            if op_type == INSERT_OPERATION:
                if row["item_vector"]:
                    vector = np.frombuffer(row["item_vector"], dtype=np.float32)
                    self._infer_and_validate_dimension(vector)
                    new_k_vectors.append(vector)
                    new_k_ids.append(item_id)
                    self._deleted_ids.discard(item_id)  # Remove from tombstones if re-indexed

            elif op_type == DELETE_OPERATION:
                self._deleted_ids.add(item_id)
                # Also remove from delta if it was just added
                if item_id in new_k_ids:
                    indices_to_remove = [i for i, id in enumerate(new_k_ids) if id == item_id]
                    for i in sorted(indices_to_remove, reverse=True):
                        del new_k_vectors[i]
                        del new_k_ids[i]

        if new_k_vectors:
            assert isinstance(self._dimension, int)
            self._k_matrix = np.array(new_k_vectors).reshape(-1, self._dimension)
            self._k_ids = new_k_ids
        else:
            self._k_matrix = None
            self._k_ids = []

        self._last_seen_log_id = db_max_log_id

    def _check_and_sync(self):
        """
        Checks if the in-memory state is stale and performs a sync.
        This is the core multi-process synchronization method.
        """
        # We use the thread-local connection for the *initial* check for speed.
        cursor = self._db.connection.cursor()
        db_base_version, db_max_log_id = self._get_db_versions(cursor)

        # Fast path: If local state matches DB state, do nothing.
        if self._is_initialized and self._local_base_version == db_base_version and self._last_seen_log_id == db_max_log_id:
            return

        # Slow path: State is different.
        # We must modify this instance's in-memory state.
        if not self._is_initialized or self._local_base_version < db_base_version:
            # Compaction happened or first-time load.
            self._load_base_index(cursor, db_base_version, db_max_log_id)
        elif self._last_seen_log_id < db_max_log_id:
            # Delta-sync is needed.
            self._sync_deltas(cursor, db_max_log_id)

    def _fast_path_insert(self, vector: np.ndarray, item_id: str, new_log_id: int):
        """
        Updates the *current process's* in-memory delta index immediately
        after a write, avoiding a self-sync.
        """
        self._infer_and_validate_dimension(vector)

        with self._thread_lock:
            new_k_vectors = list(self._k_matrix) if self._k_matrix is not None else []
            new_k_ids = list(self._k_ids)

            new_k_vectors.append(vector)
            new_k_ids.append(item_id)
            self._deleted_ids.discard(item_id) # Remove from tombstones

            assert isinstance(self._dimension, int)
            self._k_matrix = np.array(new_k_vectors).reshape(-1, self._dimension)
            self._k_ids = new_k_ids
            self._last_seen_log_id = new_log_id

    def _fast_path_delete(self, item_id: str, new_log_id: int):
        """
        Updates the *current process's* in-memory tombstones immediately
        after a delete, avoiding a self-sync.
        """
        with self._thread_lock:
            self._deleted_ids.add(item_id)

            # Also remove from delta if it was just added
            if self._k_matrix is not None and item_id in self._k_ids:
                new_k_vectors = list(self._k_matrix)
                new_k_ids = list(self._k_ids)

                indices_to_remove = [i for i, id in enumerate(new_k_ids) if id == item_id]
                for i in sorted(indices_to_remove, reverse=True):
                    del new_k_vectors[i]
                    del new_k_ids[i]

                if new_k_vectors:
                    assert isinstance(self._dimension, int)
                    self._k_matrix = np.array(new_k_vectors).reshape(-1, self._dimension)
                    self._k_ids = new_k_ids
                else:
                    self._k_matrix = None
                    self._k_ids = []

            self._last_seen_log_id = new_log_id

    def search(self, vector: np.ndarray, top_k: int) -> List[Tuple[str, float]]:
        """
        Performs a hybrid O(N+k) linear search in-memory.
        Returns the top_k closest vectors by L2 distance.
        """
        self._infer_and_validate_dimension(vector)
        self._check_and_sync() # Ensures in-memory state is up-to-date

        with self._thread_lock:
            all_distances: List[float] = []
            all_ids: List[str] = []

            query_vector = vector.astype(np.float32)

            # Search Base Index (O(N))
            if self._n_matrix is not None:
                # Calculate L2 distance (squared)
                distances = np.sum((self._n_matrix - query_vector)**2, axis=1)
                all_distances.extend(distances)
                all_ids.extend(self._n_ids)

            # Search Delta Index (O(k))
            if self._k_matrix is not None:
                distances = np.sum((self._k_matrix - query_vector)**2, axis=1)
                all_distances.extend(distances)
                all_ids.extend(self._k_ids)

            if not all_ids:
                return []

            # Combine, filter, and sort
            results: Dict[str, float] = {}
            for id_str, dist in zip(all_ids, all_distances):
                if id_str not in self._deleted_ids:
                    # Keep only the best score for each ID (in case of re-indexing)
                    if id_str not in results or dist < results[id_str]:
                        results[id_str] = float(dist)

            # Sort by distance (ascending)
            sorted_results = sorted(results.items(), key=lambda item: item[1])

            # Return top_k
            return sorted_results[:top_k]

    def compact(self, cursor: sqlite3.Cursor):
        """
        Rebuilds the base index from the main collection table.
        This method is called by CollectionManager and must be wrapped in
        its *own* inter-process lock.
        """
        # Re-fetch versions inside the lock
        db_base_version, _ = self._get_db_versions(cursor)

        # Delete all entries from the change log
        cursor.execute(
            "DELETE FROM _vector_change_log WHERE collection_name = ?",
            (self._collection,)
        )

        # Increment the base version
        new_base_version = db_base_version + 1
        cursor.execute(
            "INSERT INTO beaver_collection_versions (collection_name, base_version) VALUES (?, ?) ON CONFLICT(collection_name) DO UPDATE SET base_version = excluded.base_version",
            (self._collection, new_base_version),
        )

        # Force this process to do a full reload on next search
        self._is_initialized = False

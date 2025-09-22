import io
import sqlite3
import threading
from typing import Dict, List, Set, Tuple

import faiss
import numpy as np

class VectorIndex:
    """
    Manages a persistent, high-performance hybrid vector index for a single collection.

    This class handles the complexities of a two-tiered index system (a large, on-disk
    base index and a small, in-memory delta index), crash-safe logging for additions
    and deletions, and multi-process synchronization. The vector dimension is inferred
    from the first vector indexed and then enforced. It also transparently maps
    user-provided string IDs to the internal integer IDs required by Faiss.
    """

    def __init__(self, collection_name: str, conn: sqlite3.Connection):
        """
        Initializes the VectorIndex for a specific collection.
        """
        self._collection_name = collection_name
        self._conn = conn
        # A lock to ensure thread safety for in-memory operations and synchronization checks.
        self._lock = threading.Lock()
        # Tracks the overall version of the collection this instance is aware of.
        self._local_version = -1
        # Tracks the specific version of the on-disk base index this instance has loaded.
        self._local_base_index_version = -1

        # In-memory components
        # The dimension of the vectors in this collection. Inferred from the first vector.
        self._dimension: int | None = None
        # The large, persistent Faiss index loaded from the database BLOB.
        self._base_index: faiss.Index | None = None
        # The small, in-memory Faiss index for newly added vectors ("delta").
        self._delta_index: faiss.IndexIDMap | None = None
        # A set of integer IDs for vectors that have been deleted but not yet compacted.
        self._deleted_int_ids: Set[int] = set()

        # In-memory caches for the bidirectional mapping between user-facing string IDs
        # and Faiss's internal integer IDs.
        self._str_to_int_id: Dict[str, int] = {}
        self._int_to_str_id: Dict[int, str] = {}

    def _infer_and_validate_dimension(self, vector: np.ndarray):
        """
        Infers the vector dimension from the first operation and validates
        subsequent vectors against it. This ensures data consistency.
        """
        # Get the last element of the shape tuple, which is the dimension.
        dim = vector.shape[-1]
        with self._lock:
            if self._dimension is None:
                # If this is the first vector we've seen, establish its dimension
                # as the official dimension for this entire collection.
                self._dimension = dim
            elif self._dimension != dim:
                # If a dimension is already set, all subsequent vectors must match.
                raise ValueError(
                    f"Vector dimension mismatch for collection '{self._collection_name}'. "
                    f"Expected {self._dimension}, but got {dim}."
                )

    def _get_or_create_int_id(self, str_id: str, cursor: sqlite3.Cursor) -> int:
        """
        Retrieves the integer ID for a string ID, creating it if it doesn't exist.
        This must be called within a transaction to be atomic.
        """
        # First, check our fast in-memory cache.
        if str_id in self._str_to_int_id:
            return self._str_to_int_id[str_id]

        # If not in cache, get it from the database, creating it if necessary.
        # INSERT OR IGNORE is an atomic and safe way to create a new mapping only if it's missing.
        cursor.execute(
            "INSERT OR IGNORE INTO _beaver_ann_id_mapping (collection_name, str_id) VALUES (?, ?)",
            (self._collection_name, str_id)
        )
        # Retrieve the now-guaranteed-to-exist integer ID.
        cursor.execute(
            "SELECT int_id FROM _beaver_ann_id_mapping WHERE collection_name = ? AND str_id = ?",
            (self._collection_name, str_id)
        )
        result = cursor.fetchone()
        if not result:
             # This case should be virtually impossible given the logic above.
            raise RuntimeError(f"Failed to create or retrieve int_id for {str_id}")

        int_id = result["int_id"]
        # Update our in-memory caches for future calls.
        self._str_to_int_id[str_id] = int_id
        self._int_to_str_id[int_id] = str_id
        return int_id

    def _get_db_version(self) -> int:
        """Gets the current overall version of the collection from the database."""
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT version FROM beaver_collection_versions WHERE collection_name = ?",
            (self._collection_name,),
        )
        result = cursor.fetchone()
        return result[0] if result else 0

    def _get_db_base_index_version(self) -> int:
        """Gets the version of the persistent on-disk base index from the database."""
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT base_index_version FROM _beaver_ann_indexes WHERE collection_name = ?",
            (self._collection_name,),
        )
        result = cursor.fetchone()
        return result[0] if result else 0

    def _check_and_sync(self):
        """
        Checks if the in-memory state is stale compared to the database and performs
        a fast, targeted sync if needed. This is the core of multi-process consistency.
        """
        db_version = self._get_db_version()
        if self._local_version < db_version:
            # Acquire a lock to prevent race conditions from multiple threads in the same process.
            with self._lock:
                # Double-checked locking: re-check the condition inside the lock.
                if self._local_version < db_version:
                    db_base_version = self._get_db_base_index_version()
                    # Always reload the ID mappings as they can change on any write.
                    self._load_id_mappings()
                    # Only perform the expensive reload of the base index if a compaction
                    # has occurred in another process.
                    if self._local_base_index_version < db_base_version or self._base_index is None:
                        self._load_base_index()
                    # Always sync the lightweight delta and deletion logs.
                    self._sync_delta_index_and_deletions()
                    # Update our local version to match the database, marking us as "up-to-date".
                    self._local_version = db_version

    def _load_id_mappings(self):
        """Loads the complete str <-> int ID mapping from the DB into in-memory caches."""
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT str_id, int_id FROM _beaver_ann_id_mapping WHERE collection_name = ?",
            (self._collection_name,)
        )
        # Fetch all mappings at once for efficiency.
        all_mappings = cursor.fetchall()
        self._str_to_int_id = {row["str_id"]: row["int_id"] for row in all_mappings}
        self._int_to_str_id = {v: k for k, v in self._str_to_int_id.items()}

    def _load_base_index(self):
        """Loads and deserializes the persistent base index from the database BLOB."""
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT index_data, base_index_version FROM _beaver_ann_indexes WHERE collection_name = ?",
            (self._collection_name,),
        )
        result = cursor.fetchone()
        if result and result["index_data"]:
            # The index is stored as bytes; we use an in-memory buffer to read it.
            buffer = io.BytesIO(result["index_data"])
            # Use Faiss's IO reader to deserialize the index from the buffer.
            reader = faiss.PyCallbackIOReader(buffer.read)
            self._base_index = faiss.read_index(reader)
            self._local_base_index_version = result["base_index_version"]
            # If the dimension is unknown, we can infer it from the loaded index.
            if self._dimension is None and self._base_index.ntotal > 0:
                self._dimension = self._base_index.d
        else:
            # If no base index exists in the DB yet.
            self._base_index = None
            self._local_base_index_version = result["base_index_version"] if result else 0

    def _sync_delta_index_and_deletions(self):
        """
        "Catches up" to changes by rebuilding the in-memory delta index and
        deletion set from the database logs.
        """
        cursor = self._conn.cursor()
        # Sync the set of deleted integer IDs.
        cursor.execute(
            "SELECT int_id FROM _beaver_ann_deletions_log WHERE collection_name = ?",
            (self._collection_name,)
        )
        self._deleted_int_ids = {row["int_id"] for row in cursor.fetchall()}

        # Get all vectors that are in the pending log.
        cursor.execute(
            """
            SELECT p.str_id, c.item_vector
            FROM _beaver_ann_pending_log p
            JOIN beaver_collections c ON p.str_id = c.item_id AND p.collection_name = c.collection
            WHERE p.collection_name = ?
            """,
            (self._collection_name,)
        )
        pending_items = cursor.fetchall()

        if pending_items:
            # Convert fetched data into numpy arrays.
            vectors = np.array([np.frombuffer(row["item_vector"], dtype=np.float32) for row in pending_items])
            if self._dimension is None:
                self._dimension = vectors[0].shape[-1]

            item_int_ids = np.array([self._str_to_int_id[row["str_id"]] for row in pending_items], dtype=np.int64)

            # Reshape and validate dimensions for consistency.
            if vectors.ndim == 1:
                vectors = vectors.reshape(-1, self._dimension)
            if vectors.shape[1] != self._dimension:
                raise ValueError(f"Inconsistent vector dimensions in pending log for '{self._collection_name}'.")

            # Rebuild the delta index from scratch with all current pending items.
            self._delta_index = faiss.IndexIDMap(faiss.IndexFlatL2(self._dimension))
            self._delta_index.add_with_ids(vectors, item_int_ids)
        else:
            # If there are no pending items, there's no delta index.
            self._delta_index = None

    def index(self, item_id: str, vector: np.ndarray, cursor: sqlite3.Cursor):
        """
        Logs a vector for future persistence and adds it to the in-memory delta index.
        This method must be called within a transaction managed by CollectionManager.
        """
        # Enforce dimension consistency for the incoming vector.
        self._infer_and_validate_dimension(vector)
        # Get or create the persistent integer ID for this string ID.
        int_id = self._get_or_create_int_id(item_id, cursor)

        # Add the string ID to the log for other processes to sync.
        cursor.execute(
            "INSERT OR IGNORE INTO _beaver_ann_pending_log (collection_name, str_id) VALUES (?, ?)",
            (self._collection_name, item_id),
        )
        # Create the delta index if this is the first item added.
        if self._delta_index is None:
            self._delta_index = faiss.IndexIDMap(faiss.IndexFlatL2(self._dimension))

        # Add the vector to the live in-memory delta index for immediate searchability.
        vector_2d = vector.reshape(1, -1).astype(np.float32)
        item_id_arr = np.array([int_id], dtype=np.int64)
        self._delta_index.add_with_ids(vector_2d, item_id_arr)

    def drop(self, item_id: str, cursor: sqlite3.Cursor):
        """
        Logs a document ID for deletion ("tombstone"). This must be called
        within a transaction managed by CollectionManager.
        """
        # Get the corresponding integer ID from our in-memory cache.
        int_id = self._str_to_int_id.get(item_id)
        if int_id is not None:
            # Add the integer ID to the deletion log.
            cursor.execute(
                "INSERT INTO _beaver_ann_deletions_log (collection_name, int_id) VALUES (?, ?)",
                (self._collection_name, int_id),
            )
            # Also add to the live in-memory deletion set.
            self._deleted_int_ids.add(int_id)

    def search(self, vector: np.ndarray, top_k: int) -> List[Tuple[str, float]]:
        """
        Performs a hybrid search and returns results with original string IDs.
        """
        # Validate the query vector and ensure our in-memory state is up-to-date.
        self._infer_and_validate_dimension(vector)
        self._check_and_sync()

        query_vector = vector.reshape(1, -1).astype(np.float32)
        all_distances: List[float] = []
        all_ids: List[int] = []

        # Search the large, persistent base index if it exists.
        if self._base_index and self._base_index.ntotal > 0:
            distances, int_ids = self._base_index.search(query_vector, top_k)
            all_distances.extend(distances[0])
            all_ids.extend(int_ids[0])

        # Search the small, in-memory delta index if it exists.
        if self._delta_index and self._delta_index.ntotal > 0:
            distances, int_ids = self._delta_index.search(query_vector, top_k)
            all_distances.extend(distances[0])
            all_ids.extend(int_ids[0])

        if not all_ids:
            return []

        # Combine results from both indexes and sort by distance.
        results = sorted(zip(all_distances, all_ids), key=lambda x: x[0])

        # Filter the results to remove duplicates and deleted items.
        final_results: List[Tuple[str, float]] = []
        seen_ids = set()
        for dist, int_id in results:
            # Faiss uses -1 for invalid IDs.
            if int_id != -1 and int_id not in self._deleted_int_ids and int_id not in seen_ids:
                # Map the internal integer ID back to the user's string ID.
                str_id = self._int_to_str_id.get(int_id)
                if str_id:
                    final_results.append((str_id, dist))
                    seen_ids.add(int_id)
                    # Stop once we have enough results.
                    if len(final_results) == top_k:
                        break

        return final_results

    def compact(self):
        """
        (Background Task) Rebuilds the base index from the main collection,
        incorporating all pending additions and permanently applying deletions.
        """
        # If the dimension is unknown, try to learn it from the logs before proceeding.
        if self._dimension is None:
            self._check_and_sync()
            if self._dimension is None: return # Nothing to compact.

        # Step 1: Take a snapshot of the logs. This defines the scope of this compaction run.
        cursor = self._conn.cursor()
        cursor.execute("SELECT str_id FROM _beaver_ann_pending_log WHERE collection_name = ?", (self._collection_name,))
        pending_str_ids = {row["str_id"] for row in cursor.fetchall()}
        cursor.execute("SELECT int_id FROM _beaver_ann_deletions_log WHERE collection_name = ?", (self._collection_name,))
        deleted_int_ids_snapshot = {row["int_id"] for row in cursor.fetchall()}

        deleted_str_ids_snapshot = {self._int_to_str_id[int_id] for int_id in deleted_int_ids_snapshot if int_id in self._int_to_str_id}

        # Step 2: Fetch all vectors from the main table that haven't been marked for deletion.
        # This is the long-running part that happens "offline" in a background thread.
        if not deleted_str_ids_snapshot:
            cursor.execute("SELECT item_id, item_vector FROM beaver_collections WHERE collection = ?", (self._collection_name,))
        else:
            cursor.execute(
                f"SELECT item_id, item_vector FROM beaver_collections WHERE collection = ? AND item_id NOT IN ({','.join('?' for _ in deleted_str_ids_snapshot)})",
                (self._collection_name, *deleted_str_ids_snapshot)
            )

        all_valid_vectors = cursor.fetchall()

        # Step 3: Build the new, clean base index in memory.
        if not all_valid_vectors:
            new_index = None
        else:
            int_ids = np.array([self._str_to_int_id[row["item_id"]] for row in all_valid_vectors], dtype=np.int64)
            vectors = np.array([np.frombuffer(row["item_vector"], dtype=np.float32) for row in all_valid_vectors])
            new_index = faiss.IndexIDMap(faiss.IndexFlatL2(self._dimension))
            new_index.add_with_ids(vectors, int_ids)

        # Step 4: Serialize the newly built index to a byte buffer.
        index_data = None
        if new_index:
            buffer = io.BytesIO()
            writer = faiss.PyCallbackIOWriter(buffer.write)
            faiss.write_index(new_index, writer)
            index_data = buffer.getvalue()

        # Step 5: Perform the atomic swap in the database. This is a fast, transactional write.
        with self._conn:
            # Increment the overall collection version to signal a change.
            self._conn.execute("INSERT INTO beaver_collection_versions (collection_name, version) VALUES (?, 1) ON CONFLICT(collection_name) DO UPDATE SET version = version + 1", (self._collection_name,))
            new_version = self._get_db_version()

            # Update the on-disk base index and its version number.
            self._conn.execute("INSERT INTO _beaver_ann_indexes (collection_name, index_data, base_index_version) VALUES (?, ?, ?) ON CONFLICT(collection_name) DO UPDATE SET index_data = excluded.index_data, base_index_version = excluded.base_index_version", (self._collection_name, index_data, new_version))

            # Atomically clear the log entries that were included in this compaction run.
            if pending_str_ids:
                self._conn.execute(f"DELETE FROM _beaver_ann_pending_log WHERE collection_name = ? AND str_id IN ({','.join('?' for _ in pending_str_ids)})", (self._collection_name, *pending_str_ids))
            if deleted_int_ids_snapshot:
                self._conn.execute(f"DELETE FROM _beaver_ann_deletions_log WHERE collection_name = ? AND int_id IN ({','.join('?' for _ in deleted_int_ids_snapshot)})", (self._collection_name, *deleted_int_ids_snapshot))

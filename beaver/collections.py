import json
import sqlite3
import uuid
from enum import Enum
from typing import Any, List, Literal, Set

import numpy as np
from scipy.spatial import cKDTree


class WalkDirection(Enum):
    OUTGOING = "outgoing"
    INCOMING = "incoming"


class Document:
    """A data class representing a single item in a collection."""

    def __init__(
        self, embedding: list[float] | None = None, id: str | None = None, **metadata
    ):
        self.id = id or str(uuid.uuid4())

        if embedding is None:
            self.embedding = None
        else:
            if not isinstance(embedding, list) or not all(
                isinstance(x, (int, float)) for x in embedding
            ):
                raise TypeError("Embedding must be a list of numbers.")
            self.embedding = np.array(embedding, dtype=np.float32)

        for key, value in metadata.items():
            setattr(self, key, value)

    def to_dict(self) -> dict[str, Any]:
        """Serializes the document's metadata to a dictionary."""
        metadata = self.__dict__.copy()
        metadata.pop("embedding", None)
        metadata.pop("id", None)
        return metadata

    def __repr__(self):
        metadata_str = ", ".join(f"{k}={v!r}" for k, v in self.to_dict().items())
        return f"Document(id='{self.id}', {metadata_str})"


class CollectionManager:
    """
    A wrapper for multi-modal collection operations with an in-memory ANN index,
    FTS, and graph capabilities.
    """

    def __init__(self, name: str, conn: sqlite3.Connection):
        self._name = name
        self._conn = conn
        self._kdtree: cKDTree | None = None
        self._doc_ids: List[str] = []
        self._local_index_version = -1  # Version of the in-memory index

    def _flatten_metadata(self, metadata: dict, prefix: str = "") -> dict[str, str]:
        """Flattens a nested dictionary and filters for string values."""
        flat_dict = {}
        for key, value in metadata.items():
            new_key = f"{prefix}__{key}" if prefix else key
            if isinstance(value, dict):
                flat_dict.update(self._flatten_metadata(value, new_key))
            elif isinstance(value, str):
                flat_dict[new_key] = value
        return flat_dict

    def _get_db_version(self) -> int:
        """Gets the current version of the collection from the database."""
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT version FROM beaver_collection_versions WHERE collection_name = ?",
            (self._name,),
        )
        result = cursor.fetchone()
        return result[0] if result else 0

    def _is_index_stale(self) -> bool:
        """Checks if the in-memory index is out of sync with the DB."""
        if self._local_index_version == -1:
            return True
        return self._local_index_version < self._get_db_version()

    def index(self, document: Document, *, fts: bool = True):
        """Indexes a Document, performing an upsert and updating the FTS index."""
        with self._conn:
            if fts:
                self._conn.execute(
                    "DELETE FROM beaver_fts_index WHERE collection = ? AND item_id = ?",
                    (self._name, document.id),
                )
                string_fields = self._flatten_metadata(document.to_dict())
                if string_fields:
                    fts_data = [
                        (self._name, document.id, path, content)
                        for path, content in string_fields.items()
                    ]
                    self._conn.executemany(
                        "INSERT INTO beaver_fts_index (collection, item_id, field_path, field_content) VALUES (?, ?, ?, ?)",
                        fts_data,
                    )

            self._conn.execute(
                "INSERT OR REPLACE INTO beaver_collections (collection, item_id, item_vector, metadata) VALUES (?, ?, ?, ?)",
                (
                    self._name,
                    document.id,
                    (
                        document.embedding.tobytes()
                        if document.embedding is not None
                        else None
                    ),
                    json.dumps(document.to_dict()),
                ),
            )
            # Atomically increment the collection's version number
            self._conn.execute(
                """
                INSERT INTO beaver_collection_versions (collection_name, version) VALUES (?, 1)
                ON CONFLICT(collection_name) DO UPDATE SET version = version + 1
                """,
                (self._name,),
            )

    def drop(self, document: Document):
        """Removes a document and all its associated data from the collection."""
        if not isinstance(document, Document):
            raise TypeError("Item to drop must be a Document object.")
        with self._conn:
            self._conn.execute(
                "DELETE FROM beaver_collections WHERE collection = ? AND item_id = ?",
                (self._name, document.id),
            )
            self._conn.execute(
                "DELETE FROM beaver_fts_index WHERE collection = ? AND item_id = ?",
                (self._name, document.id),
            )
            self._conn.execute(
                "DELETE FROM beaver_edges WHERE collection = ? AND (source_item_id = ? OR target_item_id = ?)",
                (self._name, document.id, document.id),
            )
            self._conn.execute(
                """
                INSERT INTO beaver_collection_versions (collection_name, version) VALUES (?, 1)
                ON CONFLICT(collection_name) DO UPDATE SET version = version + 1
                """,
                (self._name,),
            )

    def __iter__(self):
        """Returns an iterator over all documents in the collection."""
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT item_id, item_vector, metadata FROM beaver_collections WHERE collection = ?",
            (self._name,),
        )
        for row in cursor:
            embedding = (
                np.frombuffer(row["item_vector"], dtype=np.float32).tolist()
                if row["item_vector"]
                else None
            )
            yield Document(
                id=row["item_id"], embedding=embedding, **json.loads(row["metadata"])
            )
        cursor.close()

    def refresh(self):
        """Forces a rebuild of the in-memory ANN index from data in SQLite."""
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT item_id, item_vector FROM beaver_collections WHERE collection = ? AND item_vector IS NOT NULL",
            (self._name,),
        )
        vectors, self._doc_ids = [], []
        for row in cursor.fetchall():
            self._doc_ids.append(row["item_id"])
            vectors.append(np.frombuffer(row["item_vector"], dtype=np.float32))

        self._kdtree = cKDTree(vectors) if vectors else None
        self._local_index_version = self._get_db_version()

    def search(
        self, vector: list[float], top_k: int = 10
    ) -> list[tuple[Document, float]]:
        """Performs a fast approximate nearest neighbor search."""
        if self._is_index_stale():
            self.refresh()
        if not self._kdtree:
            return []

        if top_k > len(self._doc_ids):
            top_k = len(self._doc_ids)

        distances, indices = self._kdtree.query(
            np.array(vector, dtype=np.float32), k=top_k
        )
        if top_k == 1:
            distances, indices = [distances], [indices]

        result_ids = [self._doc_ids[i] for i in indices]
        placeholders = ",".join("?" for _ in result_ids)
        sql = f"SELECT item_id, item_vector, metadata FROM beaver_collections WHERE collection = ? AND item_id IN ({placeholders})"

        cursor = self._conn.cursor()
        rows = cursor.execute(sql, (self._name, *result_ids)).fetchall()
        row_map = {row["item_id"]: row for row in rows}

        results = []
        for i, doc_id in enumerate(result_ids):
            row = row_map.get(doc_id)
            if row:
                embedding = np.frombuffer(row["item_vector"], dtype=np.float32).tolist()
                doc = Document(
                    id=doc_id, embedding=embedding, **json.loads(row["metadata"])
                )
                results.append((doc, float(distances[i])))
        return results

    def match(
        self, query: str, on_field: str | None = None, top_k: int = 10
    ) -> list[tuple[Document, float]]:
        """Performs a full-text search on indexed string fields."""
        cursor = self._conn.cursor()
        sql_query = """
            SELECT t1.item_id, t1.item_vector, t1.metadata, fts.rank
            FROM beaver_collections AS t1 JOIN (
                SELECT DISTINCT item_id, rank FROM beaver_fts_index
                WHERE beaver_fts_index MATCH ? {} ORDER BY rank LIMIT ?
            ) AS fts ON t1.item_id = fts.item_id
            WHERE t1.collection = ? ORDER BY fts.rank
        """
        params, field_filter_sql = [], ""
        if on_field:
            field_filter_sql = "AND field_path = ?"
            params.extend([query, on_field])
        else:
            params.append(query)
        params.extend([top_k, self._name])

        rows = cursor.execute(
            sql_query.format(field_filter_sql), tuple(params)
        ).fetchall()
        results = []
        for row in rows:
            embedding = (
                np.frombuffer(row["item_vector"], dtype=np.float32).tolist()
                if row["item_vector"]
                else None
            )
            doc = Document(
                id=row["item_id"], embedding=embedding, **json.loads(row["metadata"])
            )
            results.append((doc, row["rank"]))
        return results

    def connect(
        self, source: Document, target: Document, label: str, metadata: dict = None
    ):
        """Creates a directed edge between two documents."""
        if not isinstance(source, Document) or not isinstance(target, Document):
            raise TypeError("Source and target must be Document objects.")
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO beaver_edges (collection, source_item_id, target_item_id, label, metadata) VALUES (?, ?, ?, ?, ?)",
                (
                    self._name,
                    source.id,
                    target.id,
                    label,
                    json.dumps(metadata) if metadata else None,
                ),
            )

    def neighbors(self, doc: Document, label: str | None = None) -> list[Document]:
        """Retrieves the neighboring documents connected to a given document."""
        sql = "SELECT t1.item_id, t1.item_vector, t1.metadata FROM beaver_collections AS t1 JOIN beaver_edges AS t2 ON t1.item_id = t2.target_item_id AND t1.collection = t2.collection WHERE t2.collection = ? AND t2.source_item_id = ?"
        params = [self._name, doc.id]
        if label:
            sql += " AND t2.label = ?"
            params.append(label)

        rows = self._conn.cursor().execute(sql, tuple(params)).fetchall()
        return [
            Document(
                id=row["item_id"],
                embedding=(
                    np.frombuffer(row["item_vector"], dtype=np.float32).tolist()
                    if row["item_vector"]
                    else None
                ),
                **json.loads(row["metadata"]),
            )
            for row in rows
        ]

    def walk(
        self,
        source: Document,
        labels: List[str],
        depth: int,
        *,
        direction: Literal[
            WalkDirection.OUTGOING, WalkDirection.INCOMING
        ] = WalkDirection.OUTGOING,
    ) -> List[Document]:
        """Performs a graph traversal (BFS) from a starting document."""
        if not isinstance(source, Document):
            raise TypeError("The starting point must be a Document object.")
        if depth <= 0:
            return []

        source_col, target_col = (
            ("source_item_id", "target_item_id")
            if direction == WalkDirection.OUTGOING
            else ("target_item_id", "source_item_id")
        )
        sql = f"""
            WITH RECURSIVE walk_bfs(item_id, current_depth) AS (
                SELECT ?, 0
                UNION ALL
                SELECT edges.{target_col}, bfs.current_depth + 1
                FROM beaver_edges AS edges JOIN walk_bfs AS bfs ON edges.{source_col} = bfs.item_id
                WHERE edges.collection = ? AND bfs.current_depth < ? AND edges.label IN ({','.join('?' for _ in labels)})
            )
            SELECT DISTINCT t1.item_id, t1.item_vector, t1.metadata
            FROM beaver_collections AS t1 JOIN walk_bfs AS bfs ON t1.item_id = bfs.item_id
            WHERE t1.collection = ? AND bfs.current_depth > 0
        """
        params = [source.id, self._name, depth] + labels + [self._name]

        rows = self._conn.cursor().execute(sql, tuple(params)).fetchall()
        return [
            Document(
                id=row["item_id"],
                embedding=(
                    np.frombuffer(row["item_vector"], dtype=np.float32).tolist()
                    if row["item_vector"]
                    else None
                ),
                **json.loads(row["metadata"]),
            )
            for row in rows
        ]


def rerank(
    *results: list[Document],
    weights: list[float] | None = None,
    k: int = 60
) -> list[Document]:
    """
    Reranks documents from multiple search result lists using Reverse Rank Fusion (RRF).
    This function is specifically designed to work with beaver.collections.Document objects.

    Args:
        results (sequence of list[Document]): A sequence of search result lists, where each
            inner list contains Document objects.
        weights (list[float], optional): A list of weights corresponding to each
            result list. If None, all lists are weighted equally. Defaults to None.
        k (int, optional): A constant used in the RRF formula. Defaults to 60.

    Returns:
        list[Document]: A single, reranked list of unique Document objects, sorted
        by their fused rank score in descending order.
    """
    if not results:
        return []

    # Assign a default weight of 1.0 if none are provided
    if weights is None:
        weights = [1.0] * len(results)

    if len(results) != len(weights):
        raise ValueError("The number of result lists must match the number of weights.")

    # Use dictionaries to store scores and unique documents by their ID
    rrf_scores: dict[str, float] = {}
    doc_store: dict[str, Document] = {}

    # Iterate through each list of Document objects and its weight
    for result_list, weight in zip(results, weights):
        for rank, doc in enumerate(result_list):
            # Use the .id attribute from the Document object
            doc_id = doc.id
            if doc_id not in doc_store:
                doc_store[doc_id] = doc

            # Calculate the reciprocal rank score, scaled by the weight
            score = weight * (1 / (k + rank))

            # Add the score to the document's running total
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + score

    # Sort the document IDs by their final aggregated scores
    sorted_doc_ids = sorted(rrf_scores.keys(), key=rrf_scores.get, reverse=True)

    # Return the final list of Document objects in the new, reranked order
    return [doc_store[doc_id] for doc_id in sorted_doc_ids]

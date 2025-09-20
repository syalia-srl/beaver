import json
import sqlite3
import uuid
from enum import Enum
from typing import Any, List, Literal, Set

import numpy as np
from scipy.spatial import KDTree


# --- Fuzzy Search Helper Functions ---

def _levenshtein_distance(s1: str, s2: str) -> int:
    """Calculates the Levenshtein distance between two strings."""
    if len(s1) < len(s2):
        return _levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]


def _get_trigrams(text: str) -> set[str]:
    """Generates a set of 3-character trigrams from a string."""
    if not text or len(text) < 3:
        return set()
    return {text[i:i+3] for i in range(len(text) - 2)}


def _sliding_window_levenshtein(query: str, content: str, fuzziness: int) -> int:
    """
    Finds the best Levenshtein match for a query within a larger text
    by comparing it against relevant substrings.
    """
    query_tokens = query.lower().split()
    content_tokens = content.lower().split()
    query_len = len(query_tokens)
    if query_len == 0:
        return 0

    min_dist = float('inf')
    query_norm = " ".join(query_tokens)

    # The window size can be slightly smaller or larger than the query length
    # to account for missing or extra words in a fuzzy match.
    for window_size in range(max(1, query_len - fuzziness), query_len + fuzziness + 1):
        if window_size > len(content_tokens):
            continue
        for i in range(len(content_tokens) - window_size + 1):
            window_text = " ".join(content_tokens[i:i+window_size])
            dist = _levenshtein_distance(query_norm, window_text)
            if dist < min_dist:
                min_dist = dist

    return int(min_dist)


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
        self._kdtree: KDTree | None = None
        self._doc_ids: List[str] = []
        self._local_index_version = -1  # Version of the in-memory index

    def _flatten_metadata(self, metadata: dict, prefix: str = "") -> dict[str, Any]:
        """Flattens a nested dictionary for indexing."""
        flat_dict = {}
        for key, value in metadata.items():
            new_key = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                flat_dict.update(self._flatten_metadata(value, new_key))
            else:
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

    def index(
        self,
        document: Document,
        *,
        fts: bool | list[str] = True,
        fuzzy: bool = False
    ):
        """
        Indexes a Document, including vector, FTS, and fuzzy search data.
        The entire operation is performed in a single atomic transaction.
        """
        with self._conn:
            # Step 1: Core Document and Vector Storage (Unaffected by FTS/Fuzzy)
            self._conn.execute(
                "INSERT OR REPLACE INTO beaver_collections (collection, item_id, item_vector, metadata) VALUES (?, ?, ?, ?)",
                (
                    self._name,
                    document.id,
                    document.embedding.tobytes() if document.embedding is not None else None,
                    json.dumps(document.to_dict()),
                ),
            )

            # Step 2: FTS and Fuzzy Indexing
            # First, clean up old index data for this document
            self._conn.execute("DELETE FROM beaver_fts_index WHERE collection = ? AND item_id = ?", (self._name, document.id))
            self._conn.execute("DELETE FROM beaver_trigrams WHERE collection = ? AND item_id = ?", (self._name, document.id))

            # Determine which string fields to index
            flat_metadata = self._flatten_metadata(document.to_dict())
            fields_to_index: dict[str, str] = {}
            if isinstance(fts, list):
                fields_to_index = {k: v for k, v in flat_metadata.items() if k in fts and isinstance(v, str)}
            elif fts:
                fields_to_index = {k: v for k, v in flat_metadata.items() if isinstance(v, str)}

            if fields_to_index:
                # FTS indexing
                fts_data = [(self._name, document.id, path, content) for path, content in fields_to_index.items()]
                self._conn.executemany(
                    "INSERT INTO beaver_fts_index (collection, item_id, field_path, field_content) VALUES (?, ?, ?, ?)",
                    fts_data,
                )

                # Fuzzy indexing (if enabled)
                if fuzzy:
                    trigram_data = []
                    for path, content in fields_to_index.items():
                        for trigram in _get_trigrams(content.lower()):
                            trigram_data.append((self._name, document.id, path, trigram))
                    if trigram_data:
                        self._conn.executemany(
                            "INSERT INTO beaver_trigrams (collection, item_id, field_path, trigram) VALUES (?, ?, ?, ?)",
                            trigram_data,
                        )

            # Step 3: Update Collection Version
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
                "DELETE FROM beaver_trigrams WHERE collection = ? AND item_id = ?",
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

        self._kdtree = KDTree(vectors) if vectors else None
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
        self,
        query: str,
        *,
        on: list[str] | None = None,
        top_k: int = 10,
        fuzziness: int = 0
    ) -> list[tuple[Document, float]]:
        """
        Performs a full-text or fuzzy search on indexed string fields.

        Args:
            query: The search query string.
            on: An optional list of fields to restrict the search to.
            top_k: The maximum number of results to return.
            fuzziness: The Levenshtein distance for fuzzy matching.
                       If 0, performs an exact FTS search.
                       If > 0, performs a fuzzy search.
        """
        if fuzziness == 0:
            return self._perform_fts_search(query, on, top_k)
        else:
            return self._perform_fuzzy_search(query, on, top_k, fuzziness)

    def _perform_fts_search(
        self, query: str, on: list[str] | None, top_k: int
    ) -> list[tuple[Document, float]]:
        """Performs a standard FTS search."""
        cursor = self._conn.cursor()
        sql_query = """
            SELECT t1.item_id, t1.item_vector, t1.metadata, fts.rank
            FROM beaver_collections AS t1 JOIN (
                SELECT DISTINCT item_id, rank FROM beaver_fts_index
                WHERE beaver_fts_index MATCH ? {} ORDER BY rank LIMIT ?
            ) AS fts ON t1.item_id = fts.item_id
            WHERE t1.collection = ? ORDER BY fts.rank
        """
        params: list[Any] = [query]
        field_filter_sql = ""
        if on:
            placeholders = ",".join("?" for _ in on)
            field_filter_sql = f"AND field_path IN ({placeholders})"
            params.extend(on)

        params.extend([top_k, self._name])
        rows = cursor.execute(sql_query.format(field_filter_sql), tuple(params)).fetchall()
        results = []
        for row in rows:
            embedding = (
                np.frombuffer(row["item_vector"], dtype=np.float32).tolist()
                if row["item_vector"] else None
            )
            doc = Document(id=row["item_id"], embedding=embedding, **json.loads(row["metadata"]))
            results.append((doc, row["rank"]))
        return results

    def _get_trigram_candidates(self, query: str, on: list[str] | None) -> set[str]:
        """
        Gets document IDs that meet a trigram similarity threshold with the query.
        """
        query_trigrams = _get_trigrams(query.lower())
        if not query_trigrams:
            return set()

        # Optimization: Only consider documents that share a significant number of trigrams.
        # This threshold dramatically reduces the number of candidates for the expensive
        # Levenshtein check. A 30% threshold is a reasonable starting point.
        similarity_threshold = int(len(query_trigrams) * 0.3)
        if similarity_threshold == 0:
            return set()

        cursor = self._conn.cursor()
        sql = """
            SELECT item_id FROM beaver_trigrams
            WHERE collection = ? AND trigram IN ({}) {}
            GROUP BY item_id
            HAVING COUNT(DISTINCT trigram) >= ?
        """
        params: list[Any] = [self._name]
        trigram_placeholders = ",".join("?" for _ in query_trigrams)
        params.extend(query_trigrams)

        field_filter_sql = ""
        if on:
            field_placeholders = ",".join("?" for _ in on)
            field_filter_sql = f"AND field_path IN ({field_placeholders})"
            params.extend(on)

        params.append(similarity_threshold)
        cursor.execute(sql.format(trigram_placeholders, field_filter_sql), tuple(params))
        return {row['item_id'] for row in cursor.fetchall()}

    def _perform_fuzzy_search(
        self, query: str, on: list[str] | None, top_k: int, fuzziness: int
    ) -> list[tuple[Document, float]]:
        """Performs a 3-stage fuzzy search: gather, score, and sort."""
        # Stage 1: Gather Candidates
        fts_results = self._perform_fts_search(query, on, top_k)
        fts_candidate_ids = {doc.id for doc, _ in fts_results}
        trigram_candidate_ids = self._get_trigram_candidates(query, on)
        candidate_ids = fts_candidate_ids.union(trigram_candidate_ids)
        if not candidate_ids:
            return []

        # Stage 2: Score Candidates
        cursor = self._conn.cursor()
        id_placeholders = ",".join("?" for _ in candidate_ids)
        sql_text = f"SELECT item_id, field_path, field_content FROM beaver_fts_index WHERE collection = ? AND item_id IN ({id_placeholders})"
        params_text: list[Any] = [self._name]
        params_text.extend(candidate_ids)
        if on:
            sql_text += f" AND field_path IN ({','.join('?' for _ in on)})"
            params_text.extend(on)

        cursor.execute(sql_text, tuple(params_text))
        candidate_texts: dict[str, dict[str, str]] = {}
        for row in cursor.fetchall():
            item_id = row['item_id']
            if item_id not in candidate_texts:
                candidate_texts[item_id] = {}
            candidate_texts[item_id][row['field_path']] = row['field_content']

        scored_candidates = []
        fts_rank_map = {doc.id: rank for doc, rank in fts_results}

        for item_id in candidate_ids:
            if item_id not in candidate_texts:
                continue
            min_dist = float('inf')
            for content in candidate_texts[item_id].values():
                dist = _sliding_window_levenshtein(query, content, fuzziness)
                if dist < min_dist:
                    min_dist = dist
            if min_dist <= fuzziness:
                scored_candidates.append({
                    "id": item_id,
                    "distance": min_dist,
                    "fts_rank": fts_rank_map.get(item_id, 0) # Use 0 for non-matches (less relevant)
                })

        # Stage 3: Sort and Fetch Results
        scored_candidates.sort(key=lambda x: (x["distance"], x["fts_rank"]))
        top_ids = [c["id"] for c in scored_candidates[:top_k]]
        if not top_ids:
            return []

        id_placeholders = ",".join("?" for _ in top_ids)
        sql_docs = f"SELECT item_id, item_vector, metadata FROM beaver_collections WHERE collection = ? AND item_id IN ({id_placeholders})"
        cursor.execute(sql_docs, (self._name, *top_ids))
        doc_map = {row["item_id"]: Document(id=row["item_id"], embedding=(np.frombuffer(row["item_vector"], dtype=np.float32).tolist() if row["item_vector"] else None), **json.loads(row["metadata"])) for row in cursor.fetchall()}

        final_results = []
        distance_map = {c["id"]: c["distance"] for c in scored_candidates}
        for doc_id in top_ids:
            if doc_id in doc_map:
                final_results.append((doc_map[doc_id], float(distance_map[doc_id])))
        return final_results

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

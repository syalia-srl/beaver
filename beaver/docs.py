import json
import uuid
import asyncio
from typing import (
    Any,
    Iterator,
    AsyncIterator,
    List,
    Protocol,
    runtime_checkable,
    TYPE_CHECKING,
    overload,
)

from pydantic import BaseModel, Field

from .manager import AsyncBeaverBase, atomic, emits

if TYPE_CHECKING:
    from .core import AsyncBeaverDB


class Document[T](BaseModel):
    """
    Minimal document container.
    """

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    body: T
    score: float | None = None


def _flatten_document(
    data: Any, parent_key: str = "", sep: str = "."
) -> Iterator[tuple[str, str]]:
    """
    Recursively yields (path, value) for all string leaf nodes in a dictionary/model.
    """
    if isinstance(data, BaseModel):
        data = data.model_dump()

    if isinstance(data, dict):
        for k, v in data.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            yield from _flatten_document(v, new_key, sep=sep)
    elif isinstance(data, list):
        for v in data:
            if isinstance(v, (dict, list)):
                yield from _flatten_document(v, parent_key, sep=sep)
            elif isinstance(v, str):
                yield parent_key, v
    elif isinstance(data, str):
        yield parent_key, data


class DocumentQuery:
    """
    A fluent query builder for searching and filtering documents.
    """

    def __init__(self, manager: "AsyncBeaverDocuments"):
        self._manager = manager
        self._search_query: str | None = None
        self._search_fields: List[str] | None = None
        self._fuzzy_query: str | None = None
        self._filters: list[tuple[str, Any]] = []
        self._sort_field: str | None = None
        self._sort_order: str = "ASC"
        self._limit: int | None = None
        self._offset: int | None = None

    def fts(self, query: str, on: List[str] | None = None) -> "DocumentQuery":
        """Adds a Full-Text Search (FTS) clause."""
        self._search_query = query
        self._search_fields = on
        return self

    def fuzzy(self, query: str) -> "DocumentQuery":
        """Adds a Fuzzy Search clause."""
        self._fuzzy_query = query
        return self

    def where(self, field: str, value: Any) -> "DocumentQuery":
        """Adds an exact match metadata filter."""
        self._filters.append((field, value))
        return self

    def sort(self, field: str, order: str = "ASC") -> "DocumentQuery":
        """Sorts by a metadata field."""
        self._sort_field = field
        self._sort_order = order.upper()
        return self

    def limit(self, limit: int) -> "DocumentQuery":
        self._limit = limit
        return self

    def offset(self, offset: int) -> "DocumentQuery":
        self._offset = offset
        return self

    async def execute(self) -> List[Document]:
        """Executes the built query and returns the results."""
        return await self._manager._execute_query(self)

    def __await__(self):
        """Allows `await docs.search(...)` directly."""
        return self.execute().__await__()

    async def __aiter__(self) -> AsyncIterator[Document]:
        """Allows `async for doc in docs.search(...)`."""
        results = await self.execute()
        for doc in results:
            yield doc


@runtime_checkable
class IBeaverDocuments[D](Protocol):
    """Protocol exposed to the user via BeaverBridge."""

    def index(
        self, document: D | None = None, id: str | None = None, body: Any | None = None
    ) -> Document: ...
    def get(self, id: str) -> D | None: ...
    def drop(self, id_or_document: str | D) -> None: ...
    def get_many(self, ids: List[str]) -> List[D]: ...

    # Query API
    def query(self) -> DocumentQuery: ...
    def search(self, query: str, on: List[str] | None = None) -> DocumentQuery: ...
    def fuzzy(self, query: str) -> DocumentQuery: ...

    def count(self) -> int: ...
    def clear(self) -> None: ...
    def __iter__(self) -> Iterator[D]: ...


class AsyncBeaverDocuments[T: BaseModel](AsyncBeaverBase[T]):
    """
    Manages document storage, field-aware Full-Text Search, and Fuzzy Search.

    Tables:
    - __beaver_documents__ (collection, item_id, data)
    - __beaver_fts_index__ (collection, item_id, field_path, field_content)
    - __beaver_trigrams__ (collection, item_id, trigram)
    """

    def __init__(self, name: str, db: "AsyncBeaverDB", model: type[T] | None = None):
        super().__init__(name, db, model)
        self._doc_model = Document[model] if model else Document[Any]

    def _normalize_doc(self, document, id, body) -> Document[T]:
        """Helper to unify flexible arguments into a Document instance."""
        if document:
            if not isinstance(document, Document):
                return self._doc_model(body=document, id=id or uuid.uuid4().hex)
            return document

        if body is not None:
            return self._doc_model(id=id or uuid.uuid4().hex, body=body)

        raise ValueError("Must provide either 'document' or 'body'.")

    @emits("index", payload=lambda *args, **kwargs: dict())
    @atomic
    async def index(
        self,
        document: Document[T] | None = None,
        id: str | None = None,
        body: T | None = None,
        fts: bool = True,
        fuzzy: bool = False,
    ) -> Document[T]:
        """
        Inserts or updates a document, indexing text fields for FTS and Trigrams.
        """
        doc = self._normalize_doc(document, id, body)

        # 1. Main Storage (Full JSON)
        if isinstance(doc.body, BaseModel):
            body_json = doc.body.model_dump_json()
        else:
            body_json = json.dumps(doc.body)

        await self.connection.execute(
            """
            INSERT OR REPLACE INTO __beaver_documents__ (collection, item_id, data)
            VALUES (?, ?, ?)
            """,
            (self._name, doc.id, body_json),
        )

        # 2. FTS Update (Flatten -> Delete Old -> Insert New)
        await self.connection.execute(
            "DELETE FROM __beaver_fts_index__ WHERE collection = ? AND item_id = ?",
            (self._name, doc.id),
        )

        fts_rows = []
        for field_path, content in _flatten_document(doc.body):
            if content.strip():
                fts_rows.append((self._name, doc.id, field_path, content))

        if fts:
            if fts_rows:
                await self.connection.executemany(
                    """
                    INSERT INTO __beaver_fts_index__ (collection, item_id, field_path, field_content)
                    VALUES (?, ?, ?, ?)
                    """,
                    fts_rows,
                )

        # 3. Fuzzy Index Update (Trigrams)
        await self.connection.execute(
            "DELETE FROM __beaver_trigrams__ WHERE collection = ? AND item_id = ?",
            (self._name, doc.id),
        )

        if fuzzy:
            # Index trigrams for the whole document content (concatenated)
            # or specific fields? For simplicity, we index all text content found.
            # This allows fuzzy matching on any text field.
            full_text = " ".join(row[3] for row in fts_rows)
            if full_text:
                await self._index_trigrams(doc.id, full_text)

        return doc

    async def _index_trigrams(self, item_id: str, text: str):
        """Generates and stores trigrams for fuzzy search."""
        clean_text = text.lower()
        if len(clean_text) < 3:
            return

        trigrams = set(clean_text[i : i + 3] for i in range(len(clean_text) - 2))

        if trigrams:
            await self.connection.executemany(
                """
                INSERT OR IGNORE INTO __beaver_trigrams__ (collection, item_id, trigram)
                VALUES (?, ?, ?)
                """,
                [(self._name, item_id, t) for t in trigrams],
            )

    @atomic
    async def get(self, id: str) -> Document[T]:
        """Retrieves a document by ID."""
        cursor = await self.connection.execute(
            "SELECT data FROM __beaver_documents__ WHERE collection = ? AND item_id = ?",
            (self._name, id),
        )
        row = await cursor.fetchone()

        if not row:
            raise KeyError(id)

        body_val = json.loads(row["data"])
        return self._doc_model(id=id, body=body_val)

    async def get_many(self, ids: List[str]) -> List[Document[T]]:
        """Batch retrieval helper."""
        if not ids:
            return []

        placeholders = ",".join("?" * len(ids))
        cursor = await self.connection.execute(
            f"SELECT item_id, data FROM __beaver_documents__ WHERE collection = ? AND item_id IN ({placeholders})",
            (self._name, *ids),
        )

        results = []
        async for row in cursor:
            body_val = json.loads(row["data"])
            results.append(self._doc_model(id=row["item_id"], body=body_val))
        return results

    @emits("drop", payload=lambda val, *args, **kwargs: dict(target=str(val)))
    @atomic
    async def drop(self, id_or_document: str | Document[T]):
        """Deletes a document by ID or instance."""
        doc_id = (
            id_or_document.id
            if isinstance(id_or_document, Document)
            else id_or_document
        )

        await self.connection.execute(
            "DELETE FROM __beaver_documents__ WHERE collection = ? AND item_id = ?",
            (self._name, doc_id),
        )
        await self.connection.execute(
            "DELETE FROM __beaver_fts_index__ WHERE collection = ? AND item_id = ?",
            (self._name, doc_id),
        )
        await self.connection.execute(
            "DELETE FROM __beaver_trigrams__ WHERE collection = ? AND item_id = ?",
            (self._name, doc_id),
        )

    # --- Query API ---

    def query(self) -> DocumentQuery:
        return DocumentQuery(self)

    async def search(
        self, query: str, on: List[str] | None = None, fuzzy: bool = False
    ):
        if fuzzy:
            return await self.query().fuzzy(query).execute()
        else:
            return await self.query().fts(query, on=on).execute()

    async def _execute_query(self, q: DocumentQuery) -> List[Document[T]]:
        """
        Compiles the DocumentQuery into SQL and executes it.
        """
        parts = ["SELECT d.item_id, d.data"]
        params = []

        # Scoring column
        if q._search_query:
            parts.append(", MIN(f.rank) as score")
        elif q._fuzzy_query:
            parts.append(", count_matches as score")
        else:
            parts.append(", NULL as score")

        parts.append("FROM __beaver_documents__ d")

        # JOINS
        if q._search_query:
            parts.append(
                "JOIN __beaver_fts_index__ f ON d.collection = f.collection AND d.item_id = f.item_id"
            )

        if q._fuzzy_query:
            # Fuzzy Logic: Find IDs with matching trigrams, count matches, and join back
            clean_query = q._fuzzy_query.lower()
            query_trigrams = [
                clean_query[i : i + 3] for i in range(len(clean_query) - 2)
            ]

            if not query_trigrams:
                return []  # Query too short for fuzzy

            placeholders = ",".join("?" * len(query_trigrams))

            # Subquery to rank by trigram matches
            subquery = f"""
                JOIN (
                    SELECT item_id, COUNT(*) as count_matches
                    FROM __beaver_trigrams__
                    WHERE collection = ? AND trigram IN ({placeholders})
                    GROUP BY item_id
                ) t ON d.item_id = t.item_id
            """
            parts.append(subquery)
            params.append(self._name)
            params.extend(query_trigrams)

        # WHERE clauses
        where = ["d.collection = ?"]
        params.append(self._name)

        if q._search_query:
            where.append("__beaver_fts_index__ MATCH ?")
            params.append(q._search_query)

            if q._search_fields:
                placeholders = ",".join("?" * len(q._search_fields))
                where.append(f"f.field_path IN ({placeholders})")
                params.extend(q._search_fields)

        if q._filters:
            for field, value in q._filters:
                where.append(f"json_extract(d.data, '$.{field}') = ?")
                params.append(value)

        parts.append("WHERE " + " AND ".join(where))

        # GROUP BY (Required for FTS when matching multiple fields to deduplicate docs)
        if q._search_query:
            parts.append("GROUP BY d.item_id")

        # ORDER BY
        if q._search_query:
            parts.append(
                "ORDER BY score"
            )  # FTS rank (lower is better usually, but here handled by sqlite)
        elif q._fuzzy_query:
            parts.append("ORDER BY score DESC")  # More trigram matches = better
        elif q._sort_field:
            parts.append(
                f"ORDER BY json_extract(d.data, '$.{q._sort_field}') {q._sort_order}"
            )
        else:
            parts.append("ORDER BY d.item_id")

        # LIMIT
        if q._limit is not None:
            parts.append("LIMIT ?")
            params.append(q._limit)
            if q._offset is not None:
                parts.append("OFFSET ?")
                params.append(q._offset)

        sql = " ".join(parts)
        cursor = await self.connection.execute(sql, tuple(params))

        results = []
        async for row in cursor:
            body_val = json.loads(row["data"])
            score = row["score"]
            doc = self._doc_model(id=row["item_id"], body=body_val, score=score)
            results.append(doc)

        return results

    async def count(self) -> int:
        cursor = await self.connection.execute(
            "SELECT COUNT(*) FROM __beaver_documents__ WHERE collection = ?",
            (self._name,),
        )
        return (await cursor.fetchone())[0]

    @atomic
    async def clear(self):
        await self.connection.execute(
            "DELETE FROM __beaver_documents__ WHERE collection = ?", (self._name,)
        )
        await self.connection.execute(
            "DELETE FROM __beaver_fts_index__ WHERE collection = ?", (self._name,)
        )
        await self.connection.execute(
            "DELETE FROM __beaver_trigrams__ WHERE collection = ?", (self._name,)
        )

    async def __aiter__(self) -> AsyncIterator[Document[T]]:
        cursor = await self.connection.execute(
            "SELECT item_id, data FROM __beaver_documents__ WHERE collection = ?",
            (self._name,),
        )
        async for row in cursor:
            body_val = json.loads(row["data"])
            yield self._doc_model(id=row["item_id"], body=body_val)

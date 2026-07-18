import json
import uuid
from typing import (
    Any,
    IO,
    Iterator,
    AsyncIterator,
    List,
    Literal,
)

from pydantic import BaseModel

from .queries import Filter
from .manager import AsyncBeaverBase, atomic, emits
from .interfaces import Document, ScoredDocument, IDocumentQuery


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


class DocumentQuery[T: BaseModel](IDocumentQuery[T]):
    """
    A fluent query builder for searching and filtering documents.
    """

    def __init__(self, manager: "AsyncBeaverDocuments[T]"):
        self._manager = manager
        self._search_query: str | None = None
        self._search_fields: List[str] | None = None
        self._fuzzy_query: str | None = None
        self._filters: list[Filter] = []
        self._sort_fields: list[tuple[str, str]] = []
        self._limit: int | None = None
        self._offset: int | None = None

    def fts(self, query: str, on: List[str] | None = None) -> "DocumentQuery[T]":
        """Adds a Full-Text Search (FTS) clause."""
        self._search_query = query
        self._search_fields = on
        return self

    def fuzzy(self, query: str) -> "DocumentQuery[T]":
        """Adds a Fuzzy Search clause."""
        self._fuzzy_query = query
        return self

    def where(self, *expressions) -> "DocumentQuery[T]":
        """Adds a metadata filter."""
        for o in expressions:
            if not isinstance(o, Filter):
                raise TypeError(
                    f"Expression {o} is invalid. Use `query(Model)` to create valid filters."
                )

        self._filters.extend(expressions)
        return self

    def sort(self, **kwargs: Literal["ASC", "DESC"]) -> "DocumentQuery[T]":
        """Sorts by a metadata field."""
        self._sort_fields.extend(kwargs.items())
        return self

    def limit(self, limit: int) -> "DocumentQuery[T]":
        self._limit = limit
        return self

    def offset(self, offset: int) -> "DocumentQuery[T]":
        self._offset = offset
        return self

    async def execute(self) -> List[ScoredDocument[T]]:
        """Executes the built query and returns the results."""
        return await self._manager._execute_query(self)

    def __await__(self):
        """Allows `await docs.search(...)` directly."""
        return self.execute().__await__()

    # Update yield type hint
    async def __aiter__(self):
        """Allows `async for doc in docs.search(...)`."""
        results = await self.execute()
        for doc in results:
            yield doc


class AsyncDocumentsBatch[T: BaseModel]:
    """Async context manager for buffered bulk document indexing.

    Buffers full Document instances on `index()` and on exit flushes via three
    coordinated `executemany` calls inside one transaction:
      1. Main storage (__beaver_documents__)
      2. FTS index (__beaver_fts_index__) — only for docs with fts=True
      3. Trigram index (__beaver_trigrams__) — only for docs with fuzzy=True

    Vector indexing is intentionally out of scope for the batched API in
    Phase 1 (per #27 §4.C).
    """

    def __init__(self, manager: "AsyncBeaverDocuments[T]"):
        self._manager = manager
        # (doc, fts_enabled, fuzzy_enabled)
        self._pending: list[tuple[Document[T], bool, bool]] = []

    def index(
        self,
        document: Document[T] | None = None,
        id: str | None = None,
        body: T | None = None,
        fts: bool = True,
        fuzzy: bool = False,
    ) -> Document[T]:
        doc = self._manager._normalize_doc(document, id, body)
        self._pending.append((doc, fts, fuzzy))
        return doc

    async def __aenter__(self) -> "AsyncDocumentsBatch[T]":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is not None or not self._pending:
            return

        doc_rows: list[tuple[str, str, str]] = []
        fts_delete_ids: list[tuple[str, str]] = []
        fts_rows: list[tuple[str, str, str, str]] = []
        trigram_delete_ids: list[tuple[str, str]] = []
        trigram_rows: list[tuple[str, str, str]] = []

        for doc, fts_enabled, fuzzy_enabled in self._pending:
            if isinstance(doc.body, BaseModel):
                body_json = doc.body.model_dump_json()
            else:
                body_json = json.dumps(doc.body)
            doc_rows.append((self._manager._name, doc.id, body_json))

            # Always clear stale FTS / trigram rows for this id (mirrors the
            # non-batched path so re-indexing the same id is consistent).
            fts_delete_ids.append((self._manager._name, doc.id))
            trigram_delete_ids.append((self._manager._name, doc.id))

            flat = list(_flatten_document(doc.body))
            if fts_enabled:
                for field_path, content in flat:
                    if content.strip():
                        fts_rows.append(
                            (self._manager._name, doc.id, field_path, content)
                        )

            if fuzzy_enabled:
                full_text = " ".join(c for _, c in flat).lower()
                if len(full_text) >= 3:
                    seen = set(full_text[i : i + 3] for i in range(len(full_text) - 2))
                    for tri in seen:
                        trigram_rows.append((self._manager._name, doc.id, tri))

        conn = self._manager.connection
        async with self._manager._internal_lock:
            async with self._manager._db.transaction():
                await conn.executemany(
                    """
                    INSERT OR REPLACE INTO __beaver_documents__
                    (collection, item_id, data) VALUES (?, ?, ?)
                    """,
                    doc_rows,
                )
                await conn.executemany(
                    "DELETE FROM __beaver_fts_index__ WHERE collection = ? AND item_id = ?",
                    fts_delete_ids,
                )
                if fts_rows:
                    await conn.executemany(
                        """
                        INSERT INTO __beaver_fts_index__
                        (collection, item_id, field_path, field_content)
                        VALUES (?, ?, ?, ?)
                        """,
                        fts_rows,
                    )
                await conn.executemany(
                    "DELETE FROM __beaver_trigrams__ WHERE collection = ? AND item_id = ?",
                    trigram_delete_ids,
                )
                if trigram_rows:
                    await conn.executemany(
                        """
                        INSERT OR IGNORE INTO __beaver_trigrams__
                        (collection, item_id, trigram) VALUES (?, ?, ?)
                        """,
                        trigram_rows,
                    )
        self._pending.clear()


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

    def query(self) -> DocumentQuery[T]:
        return DocumentQuery(self)

    async def search(
        self,
        query: str | None = None,
        on: List[str] | None = None,
        fuzzy: bool = False,
        *,
        where: list | None = None,
        sort: dict | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ):
        qb = self.query()
        if query is not None:
            qb = qb.fuzzy(query) if fuzzy else qb.fts(query, on=on)
        if where:
            qb = qb.where(*where)
        if sort:
            qb = qb.sort(**sort)
        if limit is not None:
            qb = qb.limit(limit)
        if offset is not None:
            qb = qb.offset(offset)
        return await qb.execute()

    async def _execute_query(self, q: DocumentQuery) -> List[ScoredDocument[T]]:
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
            for filter in q._filters:
                where.append(
                    f"json_extract(d.data, '$.{filter.path}') {filter.operator} ?"
                )
                params.append(filter.value)

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
        elif q._sort_fields:
            sort_expr = ", ".join(
                f"json_extract(d.data, '$.{field}') {order}"
                for field, order in q._sort_fields
            )
            parts.append(f"ORDER BY {sort_expr}")
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

            # 1. Create the clean Document (No score)
            doc = self._doc_model(id=row["item_id"], body=body_val)

            # 2. Wrap it in ScoredDocument
            # We use the generic T from self._model or Any
            result_item = ScoredDocument(document=doc, score=score)

            results.append(result_item)

        return results

    async def count(self) -> int:
        cursor = await self.connection.execute(
            "SELECT COUNT(*) FROM __beaver_documents__ WHERE collection = ?",
            (self._name,),
        )
        result = await cursor.fetchone()
        return result[0] if result else 0

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

    async def _iter_dump_items(self):
        async for doc in self:
            body_val = doc.body
            if self._model and isinstance(body_val, BaseModel):
                body_val = json.loads(body_val.model_dump_json())
            yield {"id": doc.id, "body": body_val}

    async def dump(
        self,
        fp: IO[str] | None = None,
        format: str = "json",
        indent: int = 2,
    ) -> dict | None:
        """
        Dumps all documents in this collection.
        Shape mirrors the other managers: {metadata, items: [{id, body}]} for
        JSON; one {id, body} dict per line for JSONL.
        """
        if format == "json":
            items = [item async for item in self._iter_dump_items()]
            dump_obj = {
                "metadata": {
                    "type": "Documents",
                    "name": self._name,
                    "count": len(items),
                },
                "items": items,
            }
            if fp:
                json.dump(dump_obj, fp, indent=indent)
                return None
            return dump_obj
        if format == "jsonl":
            if fp is None:
                raise ValueError("JSONL format requires fp.")
            async for item in self._iter_dump_items():
                fp.write(json.dumps(item) + "\n")
            return None
        raise ValueError(f"Unsupported format: {format!r}. Use 'json' or 'jsonl'.")

    async def load(
        self,
        fp: IO[str],
        format: str = "json",
        strategy: str = "overwrite",
    ) -> None:
        """Loads documents from a serialized dump (JSON or JSONL)."""
        if format not in ("json", "jsonl"):
            raise ValueError(f"Unsupported format: {format!r}. Use 'json' or 'jsonl'.")
        if strategy not in ("overwrite", "append"):
            raise ValueError(
                f"Unsupported strategy: {strategy!r}. Use 'overwrite' or 'append'."
            )

        if strategy == "overwrite":
            await self.clear()

        if format == "json":
            data = json.load(fp)
            for item in data.get("items", []):
                await self._load_item(item)
        else:  # jsonl
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                await self._load_item(json.loads(line))

    async def _load_item(self, item: dict) -> None:
        await self.index(id=item["id"], body=item["body"])

    def batched(self) -> AsyncDocumentsBatch[T]:
        """Returns an async context manager for buffered bulk indexing."""
        return AsyncDocumentsBatch(self)

import asyncio
import uuid
import numpy as np
import json
import sqlite3
import time
from typing import Any, AsyncIterator, Union


class BeaverDB:
    """
    An embedded, multi-modal database in a single SQLite file.
    Currently supports async pub/sub and a synchronous key-value store.
    """

    def __init__(self, db_path: str):
        """
        Initializes the database connection and creates necessary tables.

        Args:
            db_path: The path to the SQLite database file.
        """
        self._db_path = db_path
        # Enable WAL mode for better concurrency between readers and writers
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.row_factory = sqlite3.Row
        self._create_pubsub_table()
        self._create_kv_table()
        self._create_list_table()
        self._create_collections_table()
        self._create_fts_table()  # <-- Nueva llamada

    def _create_fts_table(self):
        """Creates the virtual FTS table for full text search."""
        with self._conn:
            self._conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS beaver_fts_index USING fts5(
                    collection,
                    item_id,
                    field_path,
                    field_content,
                    tokenize = 'porter'
                )
            """
            )

    def _create_pubsub_table(self):
        """Creates the pub/sub log table if it doesn't exist."""
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS beaver_pubsub_log (
                    timestamp REAL PRIMARY KEY,
                    channel_name TEXT NOT NULL,
                    message_payload TEXT NOT NULL
                )
            """
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_pubsub_channel_timestamp
                ON beaver_pubsub_log (channel_name, timestamp)
            """
            )

    def _create_kv_table(self):
        """Creates the key-value store table if it doesn't exist."""
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS _beaver_kv_store (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """
            )

    def _create_list_table(self):
        """Creates the lists table if it doesn't exist."""
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS beaver_lists (
                    list_name TEXT NOT NULL,
                    item_order REAL NOT NULL,
                    item_value TEXT NOT NULL,
                    PRIMARY KEY (list_name, item_order)
                )
            """
            )

    def _create_collections_table(self):
        """Creates the collections table if it doesn't exist."""
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS beaver_collections (
                    collection TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    item_vector BLOB,
                    metadata TEXT,
                    PRIMARY KEY (collection, item_id)
                )
            """
            )

    def close(self):
        """Closes the database connection."""
        if self._conn:
            self._conn.close()

    # --- Key-Value Store Methods ---

    def set(self, key: str, value: Any):
        """
        Stores a JSON-serializable value for a given key.
        This operation is synchronous.

        Args:
            key: The unique string identifier for the value.
            value: A JSON-serializable Python object (dict, list, str, int, etc.).

        Raises:
            TypeError: If the key is not a string or the value is not JSON-serializable.
        """
        if not isinstance(key, str):
            raise TypeError("Key must be a string.")

        try:
            json_value = json.dumps(value)
        except TypeError as e:
            raise TypeError("Value must be JSON-serializable.") from e

        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO _beaver_kv_store (key, value) VALUES (?, ?)",
                (key, json_value),
            )

    def get(self, key: str) -> Any:
        """
        Retrieves a value for a given key.
        This operation is synchronous.

        Args:
            key: The string identifier for the value.

        Returns:
            The deserialized Python object, or None if the key is not found.

        Raises:
            TypeError: If the key is not a string.
        """
        if not isinstance(key, str):
            raise TypeError("Key must be a string.")

        cursor = self._conn.cursor()
        cursor.execute("SELECT value FROM _beaver_kv_store WHERE key = ?", (key,))
        result = cursor.fetchone()
        cursor.close()

        if result:
            return json.loads(result["value"])
        return None

    # --- List Methods ---

    def list(self, name: str) -> "ListWrapper":
        """
        Returns a wrapper object for interacting with a specific list.

        Args:
            name: The name of the list.

        Returns:
            A ListWrapper instance bound to the given list name.
        """
        if not isinstance(name, str) or not name:
            raise TypeError("List name must be a non-empty string.")
        return ListWrapper(name, self._conn)

    def collection(self, name: str) -> "CollectionWrapper":
        """Returns a wrapper for interacting with a vector collection."""
        return CollectionWrapper(name, self._conn)

    # --- Asynchronous Pub/Sub Methods ---

    async def publish(self, channel_name: str, payload: Any):
        """
        Publishes a JSON-serializable message to a channel.
        This operation is asynchronous.
        """
        if not isinstance(channel_name, str) or not channel_name:
            raise ValueError("Channel name must be a non-empty string.")
        try:
            json_payload = json.dumps(payload)
        except TypeError as e:
            raise TypeError("Message payload must be JSON-serializable.") from e

        await asyncio.to_thread(self._write_publish_to_db, channel_name, json_payload)

    def _write_publish_to_db(self, channel_name, json_payload):
        """The synchronous part of the publish operation."""
        with self._conn:
            self._conn.execute(
                "INSERT INTO beaver_pubsub_log (timestamp, channel_name, message_payload) VALUES (?, ?, ?)",
                (time.time(), channel_name, json_payload),
            )

    def subscribe(self, channel_name: str) -> "Subscriber":
        """
        Subscribes to a channel, returning an async iterator.
        """
        return Subscriber(self._conn, channel_name)


class ListWrapper:
    """A wrapper providing a Pythonic interface to a list in the database."""

    def __init__(self, name: str, conn: sqlite3.Connection):
        self._name = name
        self._conn = conn

    def __len__(self) -> int:
        """Returns the number of items in the list (e.g., `len(my_list)`)."""
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM beaver_lists WHERE list_name = ?", (self._name,)
        )
        count = cursor.fetchone()[0]
        cursor.close()
        return count

    def __getitem__(self, key: Union[int, slice]) -> Any:
        """
        Retrieves an item or slice from the list (e.g., `my_list[0]`, `my_list[1:3]`).
        """
        if isinstance(key, slice):
            start, stop, step = key.indices(len(self))
            if step != 1:
                raise ValueError("Slicing with a step is not supported.")

            limit = stop - start
            if limit <= 0:
                return []

            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT item_value FROM beaver_lists WHERE list_name = ? ORDER BY item_order ASC LIMIT ? OFFSET ?",
                (self._name, limit, start),
            )
            results = [json.loads(row["item_value"]) for row in cursor.fetchall()]
            cursor.close()
            return results

        elif isinstance(key, int):
            list_len = len(self)
            if key < -list_len or key >= list_len:
                raise IndexError("List index out of range.")

            offset = key if key >= 0 else list_len + key

            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT item_value FROM beaver_lists WHERE list_name = ? ORDER BY item_order ASC LIMIT 1 OFFSET ?",
                (self._name, offset),
            )
            result = cursor.fetchone()
            cursor.close()
            return json.loads(result["item_value"]) if result else None

        else:
            raise TypeError("List indices must be integers or slices.")

    def _get_order_at_index(self, index: int) -> float:
        """Helper to get the float `item_order` at a specific index."""
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT item_order FROM beaver_lists WHERE list_name = ? ORDER BY item_order ASC LIMIT 1 OFFSET ?",
            (self._name, index),
        )
        result = cursor.fetchone()
        cursor.close()

        if result:
            return result[0]

        raise IndexError(f"{index} out of range.")

    def push(self, value: Any):
        """Pushes an item to the end of the list."""
        with self._conn:
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT MAX(item_order) FROM beaver_lists WHERE list_name = ?",
                (self._name,),
            )
            max_order = cursor.fetchone()[0] or 0.0
            new_order = max_order + 1.0

            cursor.execute(
                "INSERT INTO beaver_lists (list_name, item_order, item_value) VALUES (?, ?, ?)",
                (self._name, new_order, json.dumps(value)),
            )

    def prepend(self, value: Any):
        """Prepends an item to the beginning of the list."""
        with self._conn:
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT MIN(item_order) FROM beaver_lists WHERE list_name = ?",
                (self._name,),
            )
            min_order = cursor.fetchone()[0] or 0.0
            new_order = min_order - 1.0

            cursor.execute(
                "INSERT INTO beaver_lists (list_name, item_order, item_value) VALUES (?, ?, ?)",
                (self._name, new_order, json.dumps(value)),
            )

    def insert(self, index: int, value: Any):
        """Inserts an item at a specific index."""
        list_len = len(self)
        if index <= 0:
            self.prepend(value)
            return
        if index >= list_len:
            self.push(value)
            return

        # Midpoint insertion
        order_before = self._get_order_at_index(index - 1)
        order_after = self._get_order_at_index(index)

        new_order = order_before + (order_after - order_before) / 2.0

        with self._conn:
            self._conn.execute(
                "INSERT INTO beaver_lists (list_name, item_order, item_value) VALUES (?, ?, ?)",
                (self._name, new_order, json.dumps(value)),
            )

    def pop(self) -> Any:
        """Removes and returns the last item from the list."""
        with self._conn:
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT rowid, item_value FROM beaver_lists WHERE list_name = ? ORDER BY item_order DESC LIMIT 1",
                (self._name,),
            )
            result = cursor.fetchone()
            if not result:
                return None

            rowid_to_delete, value_to_return = result
            cursor.execute(
                "DELETE FROM beaver_lists WHERE rowid = ?", (rowid_to_delete,)
            )
            return json.loads(value_to_return)

    def deque(self) -> Any:
        """Removes and returns the first item from the list."""
        with self._conn:
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT rowid, item_value FROM beaver_lists WHERE list_name = ? ORDER BY item_order ASC LIMIT 1",
                (self._name,),
            )
            result = cursor.fetchone()
            if not result:
                return None

            rowid_to_delete, value_to_return = result
            cursor.execute(
                "DELETE FROM beaver_lists WHERE rowid = ?", (rowid_to_delete,)
            )
            return json.loads(value_to_return)


class Subscriber(AsyncIterator):
    """
    An async iterator that polls a channel for new messages.
    Designed to be used with 'async with'.
    """

    def __init__(
        self, conn: sqlite3.Connection, channel_name: str, poll_interval: float = 0.1
    ):
        self._conn = conn
        self._channel = channel_name
        self._poll_interval = poll_interval
        self._queue = asyncio.Queue()
        self._last_seen_timestamp = time.time()
        self._polling_task = None

    async def _poll_for_messages(self):
        """Background task that polls the database for new messages."""
        while True:
            try:
                new_messages = await asyncio.to_thread(self._fetch_new_messages_from_db)
                if new_messages:
                    for msg in new_messages:
                        payload = json.loads(msg["message_payload"])
                        await self._queue.put(payload)
                        self._last_seen_timestamp = msg["timestamp"]
                await asyncio.sleep(self._poll_interval)
            except asyncio.CancelledError:
                break
            except Exception:
                # In a real app, add more robust error logging
                await asyncio.sleep(self._poll_interval * 5)

    def _fetch_new_messages_from_db(self) -> list:
        """The actual synchronous database query."""
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT timestamp, message_payload FROM beaver_pubsub_log WHERE channel_name = ? AND timestamp > ? ORDER BY timestamp ASC",
            (self._channel, self._last_seen_timestamp),
        )
        results = cursor.fetchall()
        cursor.close()
        return results

    async def __aenter__(self):
        """Starts the background task."""
        self._polling_task = asyncio.create_task(self._poll_for_messages())
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Stops the background task."""
        if self._polling_task:
            self._polling_task.cancel()
            await asyncio.gather(self._polling_task, return_exceptions=True)

    def __aiter__(self):
        return self

    async def __anext__(self) -> Any:
        """Allows 'async for' to pull messages from the internal queue."""
        return await self._queue.get()


class Document:
    """A data class for a vector and its metadata, with a unique ID."""

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
        """Serializes metadata to a dictionary."""
        metadata = self.__dict__.copy()
        # Exclude internal attributes from the metadata payload
        metadata.pop("embedding", None)
        metadata.pop("id", None)
        return metadata

    def __repr__(self):
        metadata_str = ", ".join(f"{k}={v!r}" for k, v in self.to_dict().items())
        return f"Document(id='{self.id}', {metadata_str})"


class CollectionWrapper:
    """A wrapper for vector collection operations with upsert logic."""

    def __init__(self, name: str, conn: sqlite3.Connection):
        self._name = name
        self._conn = conn

    # Dentro de la clase CollectionWrapper en beaver/core.py

    def _flatten_metadata(self, metadata: dict, prefix: str = "") -> dict[str, str]:
        """
        Aplana un diccionario anidado y filtra solo los valores de tipo string.
        Ejemplo: {'a': {'b': 'c'}} -> {'a__b': 'c'}
        """
        flat_dict = {}
        for key, value in metadata.items():
            new_key = f"{prefix}__{key}" if prefix else key
            if isinstance(value, dict):
                flat_dict.update(self._flatten_metadata(value, new_key))
            elif isinstance(value, str):
                flat_dict[new_key] = value
        return flat_dict

    def index(self, document: Document, *, fts: bool = True):
        """
        Indexa un Document, realizando un upsert y actualizando el índice FTS.
        """
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
                    document.embedding.tobytes() if document.embedding is not None else None,
                    json.dumps(document.to_dict()),
                ),
            )

    def search(
        self, vector: list[float], top_k: int = 10
    ) -> list[tuple[Document, float]]:
        """
        Performs a vector search and returns Document objects.
        """
        query_vector = np.array(vector, dtype=np.float32)

        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT item_id, item_vector, metadata FROM beaver_collections WHERE collection = ?",
            (self._name,),
        )

        all_docs_data = cursor.fetchall()
        cursor.close()

        if not all_docs_data:
            return []

        results = []
        for row in all_docs_data:
            if row["item_vector"] is None:
                continue  # Skip documents without embeddings

            doc_id = row["item_id"]
            embedding = np.frombuffer(row["item_vector"], dtype=np.float32).tolist()
            metadata = json.loads(row["metadata"])

            distance = np.linalg.norm(embedding - query_vector)

            # Reconstruct the Document object with its original ID
            doc = Document(id=doc_id, embedding=list(embedding), **metadata)
            results.append((doc, float(distance)))

        results.sort(key=lambda x: x[1])
        return results[:top_k]

    def match(
        self, query: str, on_field: str | None = None, top_k: int = 10
    ) -> list[tuple[Document, float]]:
        """
        Realiza una búsqueda de texto completo en los campos de metadatos indexados.

        Args:
            query: La expresión de búsqueda (ej. "gato", "perro OR conejo").
            on_field: Opcional, el campo específico donde buscar (ej. "details__title").
            top_k: El número máximo de resultados a devolver.

        Returns:
            Una lista de tuplas (Documento, puntuación_de_relevancia).
        """
        cursor = self._conn.cursor()

        sql_query = """
            SELECT
                t1.item_id, t1.item_vector, t1.metadata, fts.rank
            FROM beaver_collections AS t1
            JOIN (
                SELECT DISTINCT item_id, rank
                FROM beaver_fts_index
                WHERE beaver_fts_index MATCH ?
                ORDER BY rank
                LIMIT ?
            ) AS fts ON t1.item_id = fts.item_id
            WHERE t1.collection = ?
            ORDER BY fts.rank
        """

        params = []
        field_filter_sql = ""

        if on_field:
            field_filter_sql = "AND field_path = ?"
            params.append(on_field)
        else:
            # Búsqueda en todos los campos
            params.append(query)

        sql_query = sql_query.format(field_filter_sql)
        params.extend([top_k, self._name])

        cursor.execute(sql_query, tuple(params))

        results = []
        for row in cursor.fetchall():
            doc_id = row["item_id"]

            if row["item_vector"] is None:
                embedding = None
            else:
                embedding = np.frombuffer(row["item_vector"], dtype=np.float32).tolist()

            metadata = json.loads(row["metadata"])
            rank = row["rank"]

            doc = Document(id=doc_id, embedding=embedding, **metadata)
            results.append((doc, rank))

        results.sort(key=lambda x: x[1])
        cursor.close()

        return results

try:
    from typing import Any, Optional, List
    import json
    from datetime import datetime, timedelta, timezone
    from fastapi import (
        FastAPI,
        HTTPException,
        Body,
        UploadFile,
        File,
        Form,
        Response,
        WebSocket,
        WebSocketDisconnect,
    )
    import uvicorn
    from pydantic import BaseModel, Field
except ImportError:
    raise ImportError(
        'Please install server dependencies with: pip install "beaver-db[server]"'
    )

from .core import BeaverDB
from .collections import Document, WalkDirection


# --- Pydantic Models for Collections ---


class IndexRequest(BaseModel):
    id: Optional[str] = None
    embedding: Optional[List[float]] = None
    metadata: dict = Field(default_factory=dict)
    fts: bool = True
    fuzzy: bool = False


class SearchRequest(BaseModel):
    vector: List[float]
    top_k: int = 10


class MatchRequest(BaseModel):
    query: str
    on: Optional[List[str]] = None
    top_k: int = 10
    fuzziness: int = 0


class ConnectRequest(BaseModel):
    source_id: str
    target_id: str
    label: str
    metadata: Optional[dict] = None


class WalkRequest(BaseModel):
    labels: List[str]
    depth: int
    direction: WalkDirection = WalkDirection.OUTGOING


class CountResponse(BaseModel):
    count: int


def build(db: BeaverDB) -> FastAPI:
    """Constructs a FastAPI instance for a given BeaverDB."""
    app = FastAPI(title="BeaverDB Server")

    # --- Dicts Endpoints ---

    @app.get("/dicts/{name}/{key}", tags=["Dicts"])
    def get_dict_item(name: str, key: str) -> Any:
        """Retrieves the value for a specific key."""
        d = db.dict(name)
        value = d.get(key)
        if value is None:
            raise HTTPException(
                status_code=404, detail=f"Key '{key}' not found in dictionary '{name}'"
            )
        return value

    @app.put("/dicts/{name}/{key}", tags=["Dicts"])
    def set_dict_item(name: str, key: str, value: Any = Body(...)):
        """Sets or updates the value for a specific key."""
        d = db.dict(name)
        d[key] = value
        return {"status": "ok"}

    @app.delete("/dicts/{name}/{key}", tags=["Dicts"])
    def delete_dict_item(name: str, key: str):
        """Deletes a key-value pair."""
        d = db.dict(name)
        try:
            del d[key]
            return {"status": "ok"}
        except KeyError:
            raise HTTPException(
                status_code=404, detail=f"Key '{key}' not found in dictionary '{name}'"
            )

    @app.get("/dicts/{name}/count", tags=["Dicts"], response_model=CountResponse)
    def get_dict_count(name: str) -> dict:
        """Retrieves the number of key-value pairs in the dictionary."""
        d = db.dict(name)
        return {"count": len(d)}

    # --- Lists Endpoints ---

    @app.get("/lists/{name}", tags=["Lists"])
    def get_list(name: str) -> list:
        """Retrieves all items in the list."""
        l = db.list(name)
        return l[:]

    @app.get("/lists/{name}/{index}", tags=["Lists"])
    def get_list_item(name: str, index: int) -> Any:
        """Retrieves the item at a specific index."""
        l = db.list(name)
        try:
            return l[index]
        except IndexError:
            raise HTTPException(
                status_code=404, detail=f"Index {index} out of bounds for list '{name}'"
            )

    @app.post("/lists/{name}", tags=["Lists"])
    def push_list_item(name: str, value: Any = Body(...)):
        """Adds an item to the end of the list."""
        l = db.list(name)
        l.push(value)
        return {"status": "ok"}

    @app.put("/lists/{name}/{index}", tags=["Lists"])
    def update_list_item(name: str, index: int, value: Any = Body(...)):
        """Updates the item at a specific index."""
        l = db.list(name)
        try:
            l[index] = value
            return {"status": "ok"}
        except IndexError:
            raise HTTPException(
                status_code=404, detail=f"Index {index} out of bounds for list '{name}'"
            )

    @app.delete("/lists/{name}/{index}", tags=["Lists"])
    def delete_list_item(name: str, index: int):
        """Deletes the item at a specific index."""
        l = db.list(name)
        try:
            del l[index]
            return {"status": "ok"}
        except IndexError:
            raise HTTPException(
                status_code=404, detail=f"Index {index} out of bounds for list '{name}'"
            )

    @app.get("/lists/{name}/count", tags=["Lists"], response_model=CountResponse)
    def get_list_count(name: str) -> dict:
        """Retrieves the number of items in the list."""
        l = db.list(name)
        return {"count": len(l)}

    # --- Queues Endpoints ---

    @app.get("/queues/{name}/peek", tags=["Queues"])
    def peek_queue_item(name: str) -> Any:
        """Retrieves the highest-priority item from the queue without removing it."""
        q = db.queue(name)
        item = q.peek()
        if item is None:
            raise HTTPException(status_code=404, detail=f"Queue '{name}' is empty")
        return item

    @app.post("/queues/{name}/put", tags=["Queues"])
    def put_queue_item(name: str, data: Any = Body(...), priority: float = Body(...)):
        """Adds an item to the queue with a specific priority."""
        q = db.queue(name)
        q.put(data=data, priority=priority)
        return {"status": "ok"}

    @app.delete("/queues/{name}/get", tags=["Queues"])
    def get_queue_item(name: str, timeout: float = 5.0) -> Any:
        """
        Atomically retrieves and removes the highest-priority item from the queue,
        blocking until an item is available or the timeout is reached.
        """
        q = db.queue(name)
        try:
            item = q.get(block=True, timeout=timeout)
            return item
        except TimeoutError:
            raise HTTPException(
                status_code=408,
                detail=f"Request timed out after {timeout}s waiting for an item in queue '{name}'",
            )
        except IndexError:
            # This case is less likely with block=True but good to handle
            raise HTTPException(status_code=404, detail=f"Queue '{name}' is empty")

    @app.get("/queues/{name}/count", tags=["Queues"], response_model=CountResponse)
    def get_queue_count(name: str) -> dict:
        """RetrieVIes the number of items currently in the queue."""
        q = db.queue(name)
        return {"count": len(q)}

    # --- Blobs Endpoints ---

    @app.get("/blobs/{name}/{key}", response_class=Response, tags=["Blobs"])
    def get_blob(name: str, key: str):
        """Retrieves a blob as a binary file."""
        blobs = db.blob(name)
        blob = blobs.get(key)
        if blob is None:
            raise HTTPException(
                status_code=404,
                detail=f"Blob with key '{key}' not found in store '{name}'",
            )
        # Return the raw bytes with a generic binary content type
        return Response(content=blob.data, media_type="application/octet-stream")

    @app.put("/blobs/{name}/{key}", tags=["Blobs"])
    async def put_blob(
        name: str,
        key: str,
        data: UploadFile = File(...),
        metadata: Optional[str] = Form(None),
    ):
        """Stores a blob (binary file) with optional JSON metadata."""
        blobs = db.blob(name)
        file_bytes = await data.read()

        meta_dict = None
        if metadata:
            try:
                meta_dict = json.loads(metadata)
            except json.JSONDecodeError:
                raise HTTPException(
                    status_code=400, detail="Invalid JSON format for metadata."
                )

        blobs.put(key=key, data=file_bytes, metadata=meta_dict)
        return {"status": "ok"}

    @app.delete("/blobs/{name}/{key}", tags=["Blobs"])
    def delete_blob(name: str, key: str):
        """Deletes a blob from the store."""
        blobs = db.blob(name)
        try:
            blobs.delete(key)
            return {"status": "ok"}
        except KeyError:
            raise HTTPException(
                status_code=404,
                detail=f"Blob with key '{key}' not found in store '{name}'",
            )

    @app.get("/blobs/{name}/count", tags=["Blobs"], response_model=CountResponse)
    def get_blob_count(name: str) -> dict:
        """Retrieves the number of blobs in the store."""
        b = db.blob(name)
        return {"count": len(b)}

    # --- Logs Endpoints ---

    @app.post("/logs/{name}", tags=["Logs"])
    def create_log_entry(name: str, data: Any = Body(...)):
        """Adds a new entry to the log."""
        log = db.log(name)
        log.log(data)
        return {"status": "ok"}

    @app.get("/logs/{name}/range", tags=["Logs"])
    def get_log_range(name: str, start: datetime, end: datetime) -> list:
        """Retrieves log entries within a specific time window."""
        log = db.log(name)
        # Ensure datetimes are timezone-aware (UTC) for correct comparison
        start_utc = (
            start.astimezone(timezone.utc)
            if start.tzinfo
            else start.replace(tzinfo=timezone.utc)
        )
        end_utc = (
            end.astimezone(timezone.utc)
            if end.tzinfo
            else end.replace(tzinfo=timezone.utc)
        )
        return log.range(start=start_utc, end=end_utc)

    @app.websocket("/logs/{name}/live", name="Logs")
    async def live_log_feed(
        websocket: WebSocket,
        name: str,
        window_seconds: int = 5,
        period_seconds: int = 1,
    ):
        """Streams live, aggregated log data over a WebSocket."""
        await websocket.accept()

        async_logs = db.log(name).as_async()

        # This simple aggregator function runs in the background and returns a
        # JSON-serializable summary of the data in the current window.
        def simple_aggregator(window):
            return {
                "count": len(window),
                "latest_timestamp": window[-1]["timestamp"] if window else None,
            }

        live_stream = async_logs.live(
            window=timedelta(seconds=window_seconds),
            period=timedelta(seconds=period_seconds),
            aggregator=simple_aggregator,
        )

        try:
            async for summary in live_stream:
                await websocket.send_json(summary)
        except WebSocketDisconnect:
            print(f"Client disconnected from log '{name}' live feed.")
        finally:
            # Cleanly close the underlying iterator and its background thread.
            live_stream.close()

    # --- Channels Endpoints ---

    @app.post("/channels/{name}/publish", tags=["Channels"])
    def publish_to_channel(name: str, payload: Any = Body(...)):
        """Publishes a message to the specified channel."""
        channel = db.channel(name)
        channel.publish(payload)
        return {"status": "ok"}

    @app.websocket("/channels/{name}/subscribe", name="Channels")
    async def subscribe_to_channel(websocket: WebSocket, name: str):
        """Subscribes to a channel and streams messages over a WebSocket."""
        await websocket.accept()

        async_channel = db.channel(name).as_async()

        try:
            async with async_channel.subscribe() as listener:
                async for message in listener.listen():
                    await websocket.send_json(message)
        except WebSocketDisconnect:
            print(f"Client disconnected from channel '{name}' subscription.")

    # --- Collections Endpoints ---

    @app.get("/collections/{name}", tags=["Collections"])
    def get_all_documents(name: str) -> List[dict]:
        """Retrieves all documents in the collection."""
        collection = db.collection(name)
        return [doc.to_dict(metadata_only=False) for doc in collection]

    @app.post("/collections/{name}/index", tags=["Collections"])
    def index_document(name: str, req: IndexRequest):
        """Indexes a document in the specified collection."""
        collection = db.collection(name)
        doc = Document(id=req.id, embedding=req.embedding, **req.metadata)
        try:
            collection.index(doc, fts=req.fts, fuzzy=req.fuzzy)
            return {"status": "ok", "id": doc.id}
        except TypeError as e:
            if "vector" in str(e):
                raise HTTPException(
                    status_code=501,
                    detail="Vector indexing requires the '[vector]' extra. Install with: pip install \"beaver-db[vector]\"",
                )
            raise e

    @app.post("/collections/{name}/search", tags=["Collections"])
    def search_collection(name: str, req: SearchRequest) -> List[dict]:
        """Performs a vector search on the collection."""
        collection = db.collection(name)
        try:
            results = collection.search(vector=req.vector, top_k=req.top_k)
            return [
                {"document": doc.to_dict(metadata_only=False), "distance": dist}
                for doc, dist in results
            ]
        except TypeError as e:
            if "vector" in str(e):
                raise HTTPException(
                    status_code=501,
                    detail="Vector search requires the '[vector]' extra. Install with: pip install \"beaver-db[vector]\"",
                )
            raise e

    @app.post("/collections/{name}/match", tags=["Collections"])
    def match_collection(name: str, req: MatchRequest) -> List[dict]:
        """Performs a full-text or fuzzy search on the collection."""
        collection = db.collection(name)
        results = collection.match(
            query=req.query, on=req.on, top_k=req.top_k, fuzziness=req.fuzziness
        )
        return [
            {"document": doc.to_dict(metadata_only=False), "score": score}
            for doc, score in results
        ]

    @app.post("/collections/{name}/connect", tags=["Collections"])
    def connect_documents(name: str, req: ConnectRequest):
        """Creates a directed edge between two documents."""
        collection = db.collection(name)
        source_doc = Document(id=req.source_id)
        target_doc = Document(id=req.target_id)
        collection.connect(
            source=source_doc, target=target_doc, label=req.label, metadata=req.metadata
        )
        return {"status": "ok"}

    @app.get("/collections/{name}/{doc_id}/neighbors", tags=["Collections"])
    def get_neighbors(
        name: str, doc_id: str, label: Optional[str] = None
    ) -> List[dict]:
        """Retrieves the neighboring documents for a given document."""
        collection = db.collection(name)
        doc = Document(id=doc_id)
        neighbors = collection.neighbors(doc, label=label)
        return [n.to_dict(metadata_only=False) for n in neighbors]

    @app.post("/collections/{name}/{doc_id}/walk", tags=["Collections"])
    def walk_graph(name: str, doc_id: str, req: WalkRequest) -> List[dict]:
        """Performs a graph traversal (BFS) from a starting document."""
        collection = db.collection(name)
        source_doc = Document(id=doc_id)
        results = collection.walk(
            source=source_doc,
            labels=req.labels,
            depth=req.depth,
            outgoing=req.direction,
        )
        return [doc.to_dict(metadata_only=False) for doc in results]

    @app.get(
        "/collections/{name}/count", tags=["Collections"], response_model=CountResponse
    )
    def get_collection_count(name: str) -> dict:
        """RetrieRetrieves the number of documents in the collection."""
        c = db.collection(name)
        return {"count": len(c)}

    return app


def serve(db_path: str, host: str, port: int):
    """Initializes and runs the Uvicorn server."""
    db = BeaverDB(db_path)
    app = build(db)
    uvicorn.run(app, host=host, port=port)

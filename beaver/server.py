try:
    from fastapi import FastAPI, HTTPException, Body
    import uvicorn
except ImportError:
    raise ImportError(
        "FastAPI and Uvicorn are required to serve the database. "
        'Please install them with `pip install "beaver-db[server]"`'
    )
from typing import Any
from .core import BeaverDB


def build(db: BeaverDB) -> FastAPI:
    """
    Constructs a FastAPI application instance for a given BeaverDB instance.

    Args:
        db: An active BeaverDB instance.

    Returns:
        A FastAPI application with all endpoints configured.
    """
    app = FastAPI(
        title="BeaverDB",
        description="A RESTful API for a BeaverDB instance.",
        version="0.1.0",
    )

    # --- Dicts Endpoints ---

    @app.get("/dicts/{name}")
    def get_all_dict_items(name: str) -> dict:
        """Retrieves all key-value pairs in a dictionary."""
        d = db.dict(name)
        return {k: v for k, v in d.items()}

    @app.get("/dicts/{name}/{key}")
    def get_dict_item(name: str, key: str) -> Any:
        """Retrieves the value for a specific key."""
        d = db.dict(name)
        try:
            return d[key]
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Key '{key}' not found in dictionary '{name}'")

    @app.post("/dicts/{name}/{key}")
    def set_dict_item(name: str, key: str, value: Any = Body(...)):
        """Sets the value for a specific key."""
        d = db.dict(name)
        d[key] = value
        return {"status": "ok"}

    @app.delete("/dicts/{name}/{key}")
    def delete_dict_item(name: str, key: str):
        """Deletes a key-value pair."""
        d = db.dict(name)
        try:
            del d[key]
            return {"status": "ok"}
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Key '{key}' not found in dictionary '{name}'")

    # --- Lists Endpoints ---

    @app.get("/lists/{name}")
    def get_list(name: str) -> list:
        """Retrieves all items in the list."""
        l = db.list(name)
        return l[:]

    @app.get("/lists/{name}/{index}")
    def get_list_item(name: str, index: int) -> Any:
        """Retrieves the item at a specific index."""
        l = db.list(name)
        try:
            return l[index]
        except IndexError:
            raise HTTPException(status_code=404, detail=f"Index {index} out of bounds for list '{name}'")

    @app.post("/lists/{name}")
    def push_list_item(name: str, value: Any = Body(...)):
        """Adds an item to the end of the list."""
        l = db.list(name)
        l.push(value)
        return {"status": "ok"}

    @app.put("/lists/{name}/{index}")
    def update_list_item(name: str, index: int, value: Any = Body(...)):
        """Updates the item at a specific index."""
        l = db.list(name)
        try:
            l[index] = value
            return {"status": "ok"}
        except IndexError:
            raise HTTPException(status_code=404, detail=f"Index {index} out of bounds for list '{name}'")

    @app.delete("/lists/{name}/{index}")
    def delete_list_item(name: str, index: int):
        """Deletes the item at a specific index."""
        l = db.list(name)
        try:
            del l[index]
            return {"status": "ok"}
        except IndexError:
            raise HTTPException(status_code=404, detail=f"Index {index} out of bounds for list '{name}'")

    # TODO: Add endpoints for all BeaverDB modalities
    # - Queues
    # - Collections
    # - Channels
    # - Logs
    # - Blobs

    @app.get("/")
    def read_root():
        return {"message": "Welcome to the BeaverDB API"}

    return app


def serve(db_path: str, host: str, port: int):
    """
    Initializes a BeaverDB instance and runs a Uvicorn server for it.

    Args:
        db_path: The path to the SQLite database file.
        host: The host to bind the server to.
        port: The port to run the server on.
    """
    db = BeaverDB(db_path)
    app = build(db)
    uvicorn.run(app, host=host, port=port)

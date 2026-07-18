from .core import BeaverDB, AsyncBeaverDB, BeaverIncompatibleSchemaError
from .docs import Document
from .events import Event
from .queries import q
from .security import Secret
from .errors import BeaverRemoteError, LocalOnlyError

__version__ = "2.1.0"


def connect(source: str, *, sync: bool = True, api_key: str | None = None):
    """Universal entry point: returns a local or remote DB based on `source`.

    - `source` starting with "http://" or "https://" → remote client.
    - Anything else → local SQLite file path.

    `sync=True` (default) returns the sync portal (`BeaverDB` / `BeaverClient`).
    `sync=False` returns the async core (`AsyncBeaverDB` / `AsyncBeaverClient`).
    `api_key` is silently ignored for local sources.
    """
    if source.startswith(("http://", "https://")):
        from .client import AsyncBeaverClient, BeaverClient

        return (
            BeaverClient(source, api_key=api_key)
            if sync
            else AsyncBeaverClient(source, api_key=api_key)
        )
    return BeaverDB(source) if sync else AsyncBeaverDB(source)


__all__ = [
    "AsyncBeaverDB",
    "BeaverDB",
    "BeaverIncompatibleSchemaError",
    "Document",
    "Secret",
    "Event",
    "q",
    "BeaverRemoteError",
    "LocalOnlyError",
    "connect",
]

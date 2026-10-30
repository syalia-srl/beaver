from .core import (
    BeaverDB,
    AsyncBeaverDB,
    BeaverIncompleteSchemaError,
    BeaverIncompatibleSchemaError,
    BeaverLegacySchemaError,
    TransactionTimeoutError,
)
from .docs import Document
from .events import Event
from .queries import q
from .security import Secret
from .errors import BeaverRemoteError, LocalOnlyError

__version__ = "2.4.1"


def connect(
    source: str,
    *,
    sync: bool = True,
    api_key: str | None = None,
    read_only: bool = False,
):
    """Universal entry point: returns a local or remote DB based on `source`.

    - `source` starting with "http://" or "https://" → remote client.
    - Anything else → local SQLite file path.

    `sync=True` (default) returns the sync portal (`BeaverDB` / `BeaverClient`).
    `sync=False` returns the async core (`AsyncBeaverDB` / `AsyncBeaverClient`).
    `api_key` is silently ignored for local sources.
    `read_only=True` opens an existing local SQLite file without modifying it;
    it is not available for remote clients.
    """
    if source.startswith(("http://", "https://")):
        if read_only:
            raise LocalOnlyError(
                "read_only=True is only available for local SQLite databases"
            )
        from .client import AsyncBeaverClient, BeaverClient

        return (
            BeaverClient(source, api_key=api_key)
            if sync
            else AsyncBeaverClient(source, api_key=api_key)
        )
    return (
        BeaverDB(source, read_only=read_only)
        if sync
        else AsyncBeaverDB(source, read_only=read_only)
    )


__all__ = [
    "AsyncBeaverDB",
    "BeaverDB",
    "BeaverIncompleteSchemaError",
    "BeaverIncompatibleSchemaError",
    "BeaverLegacySchemaError",
    "TransactionTimeoutError",
    "Document",
    "Secret",
    "Event",
    "q",
    "BeaverRemoteError",
    "LocalOnlyError",
    "connect",
]

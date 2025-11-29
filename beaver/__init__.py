from .core import BeaverDB, AsyncBeaverDB
from .docs import Document
from .events import Event
from .queries import q
from .security import Secret

__version__ = "1.3.0"

__all__ = [
    "AsyncBeaverDB",
    "BeaverDB",
    "Document",
    "Secret",
    "Event",
    "q",
]

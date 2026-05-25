"""Error envelope, exception registry, and custom exceptions for SID consumers."""

import pydantic
from pydantic import BaseModel

from .core import BeaverIncompatibleSchemaError


class BeaverRemoteError(Exception):
    """Server raised an exception whose class is not in the client's registry."""


class LocalOnlyError(Exception):
    """Remote client cannot perform a method that is only available locally."""


class ErrorEnvelope(BaseModel):
    error: str
    message: str
    detail: dict | None = None


_REGISTRY: dict[str, type[Exception]] = {
    "KeyError": KeyError,
    "ValueError": ValueError,
    "TimeoutError": TimeoutError,
    "BeaverIncompatibleSchemaError": BeaverIncompatibleSchemaError,
    "ValidationError": pydantic.ValidationError,
}


_HTTP_CODES: dict[type[Exception], int] = {
    KeyError: 404,
    TimeoutError: 409,
    pydantic.ValidationError: 422,
    BeaverIncompatibleSchemaError: 500,
    ValueError: 400,
}


def envelope_from_exception(exc: BaseException) -> ErrorEnvelope:
    """Build a wire envelope from any exception. Class name is taken from type(exc)."""
    return ErrorEnvelope(error=type(exc).__name__, message=str(exc), detail=None)


def http_code_for(exc: BaseException) -> int:
    """Pick an HTTP code for an exception; falls back to 500."""
    for cls, code in _HTTP_CODES.items():
        if isinstance(exc, cls):
            return code
    return 500


def raise_from_envelope(env: ErrorEnvelope) -> None:
    """Raise the Python exception corresponding to a wire envelope.

    Known class names → registered class; unknown → BeaverRemoteError.
    """
    cls = _REGISTRY.get(env.error)
    if cls is None:
        raise BeaverRemoteError(env.message)
    raise cls(env.message)

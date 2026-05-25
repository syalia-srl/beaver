import pytest
from pydantic import ValidationError
from beaver.errors import (
    ErrorEnvelope,
    BeaverRemoteError,
    LocalOnlyError,
    _REGISTRY,
    _HTTP_CODES,
    raise_from_envelope,
    envelope_from_exception,
)


def test_envelope_roundtrip():
    env = ErrorEnvelope(error="KeyError", message="missing", detail=None)
    serialized = env.model_dump()
    assert serialized == {"error": "KeyError", "message": "missing", "detail": None}
    restored = ErrorEnvelope.model_validate(serialized)
    assert restored == env


def test_registry_known_classes():
    assert _REGISTRY["KeyError"] is KeyError
    assert _REGISTRY["ValueError"] is ValueError
    assert _REGISTRY["ValidationError"] is ValidationError


def test_raise_from_envelope_known_class():
    env = ErrorEnvelope(error="KeyError", message="missing")
    with pytest.raises(KeyError, match="missing"):
        raise_from_envelope(env)


def test_raise_from_envelope_unknown_class():
    env = ErrorEnvelope(error="ZorkError", message="boom")
    with pytest.raises(BeaverRemoteError, match="boom"):
        raise_from_envelope(env)


def test_envelope_from_exception_known():
    env = envelope_from_exception(KeyError("foo"))
    assert env.error == "KeyError"
    assert "foo" in env.message


def test_envelope_from_exception_unknown():
    class WeirdError(Exception): pass
    env = envelope_from_exception(WeirdError("bad"))
    assert env.error == "WeirdError"
    assert env.message == "bad"


def test_http_codes_table():
    assert _HTTP_CODES[KeyError] == 404
    assert _HTTP_CODES[ValidationError] == 422


def test_local_only_error_carries_message():
    err = LocalOnlyError("dict.keys() is only available on local databases")
    assert "keys()" in str(err)

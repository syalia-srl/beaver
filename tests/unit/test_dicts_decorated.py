from beaver.dicts import AsyncBeaverDict
from beaver.api import EndpointMeta


def _meta(method_name: str) -> EndpointMeta:
    fn = getattr(AsyncBeaverDict, method_name)
    return fn.__beaver_endpoint__


def test_get_metadata():
    m = _meta("get")
    assert m.method == "GET"
    assert m.path == "/{key}"
    assert m.cli_name == "get"


def test_set_metadata():
    m = _meta("set")
    assert m.method == "PUT"
    assert m.path == "/{key}"
    assert m.body_param == "value"


def test_delete_metadata():
    m = _meta("delete")
    assert m.method == "DELETE"
    assert m.path == "/{key}"


def test_count_metadata():
    m = _meta("count")
    assert m.method == "GET"
    assert m.path == "/count"


def test_clear_metadata():
    m = _meta("clear")
    assert m.method == "POST"
    assert m.path == "/clear"


def test_contains_metadata():
    m = _meta("contains")
    assert m.method == "GET"
    assert m.path == "/{key}/contains"


def test_pop_metadata():
    m = _meta("pop")
    assert m.method == "POST"
    assert m.path == "/{key}/pop"
    assert m.body_param == "default"


def test_fetch_metadata():
    m = _meta("fetch")
    assert m.method == "GET"
    assert m.path == "/{key}/fetch"


def test_keys_is_local_only():
    assert hasattr(AsyncBeaverDict.keys, "__beaver_local_only__")
    assert "local" in AsyncBeaverDict.keys.__beaver_local_only__.lower()


def test_batched_is_local_only():
    assert hasattr(AsyncBeaverDict.batched, "__beaver_local_only__")

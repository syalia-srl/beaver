from beaver.lists import AsyncBeaverList
from beaver.api import EndpointMeta


def _meta(method_name: str) -> EndpointMeta:
    fn = getattr(AsyncBeaverList, method_name)
    return fn.__beaver_endpoint__


def test_count_metadata():
    m = _meta("count")
    assert m.method == "GET"
    assert m.path == "/count"


def test_get_metadata():
    m = _meta("get")
    assert m.method == "GET"
    assert m.path == "/item/{index}"


def test_set_metadata():
    m = _meta("set")
    assert m.method == "PUT"
    assert m.path == "/item/{index}"
    assert m.body_param == "value"


def test_delete_metadata():
    m = _meta("delete")
    assert m.method == "DELETE"
    assert m.path == "/item/{index}"


def test_contains_metadata():
    m = _meta("contains")
    assert m.method == "GET"
    assert m.path == "/contains"


def test_push_metadata():
    m = _meta("push")
    assert m.method == "POST"
    assert m.path == "/push"
    assert m.body_param == "value"


def test_prepend_metadata():
    m = _meta("prepend")
    assert m.method == "POST"
    assert m.path == "/prepend"
    assert m.body_param == "value"


def test_insert_metadata():
    m = _meta("insert")
    assert m.method == "POST"
    assert m.path == "/insert/{index}"
    assert m.body_param == "value"


def test_pop_metadata():
    m = _meta("pop")
    assert m.method == "POST"
    assert m.path == "/pop"


def test_deque_metadata():
    m = _meta("deque")
    assert m.method == "POST"
    assert m.path == "/deque"


def test_clear_metadata():
    m = _meta("clear")
    assert m.method == "POST"
    assert m.path == "/clear"


def test_dump_is_local_only():
    assert hasattr(AsyncBeaverList.dump, "__beaver_local_only__")


def test_load_is_local_only():
    assert hasattr(AsyncBeaverList.load, "__beaver_local_only__")


def test_batched_is_local_only():
    assert hasattr(AsyncBeaverList.batched, "__beaver_local_only__")

from beaver.queues import AsyncBeaverQueue
from beaver.api import EndpointMeta


def _meta(method_name: str) -> EndpointMeta:
    fn = getattr(AsyncBeaverQueue, method_name)
    return fn.__beaver_endpoint__


def test_put_metadata():
    m = _meta("put")
    assert m.method == "POST"
    assert m.path == "/put"
    assert m.body_param == "data"


def test_peek_metadata():
    m = _meta("peek")
    assert m.method == "GET"
    assert m.path == "/peek"


def test_get_metadata():
    m = _meta("get")
    assert m.method == "POST"
    assert m.path == "/get"


def test_count_metadata():
    m = _meta("count")
    assert m.method == "GET"
    assert m.path == "/count"


def test_clear_metadata():
    m = _meta("clear")
    assert m.method == "POST"
    assert m.path == "/clear"


def test_dump_is_local_only():
    assert hasattr(AsyncBeaverQueue.dump, "__beaver_local_only__")


def test_load_is_local_only():
    assert hasattr(AsyncBeaverQueue.load, "__beaver_local_only__")

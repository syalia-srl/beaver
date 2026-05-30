from beaver.logs import AsyncBeaverLog
from beaver.api import EndpointMeta


def _meta(method_name: str) -> EndpointMeta:
    fn = getattr(AsyncBeaverLog, method_name)
    return fn.__beaver_endpoint__


def test_log_metadata():
    m = _meta("log")
    assert m.method == "POST"
    assert m.path == "/log"
    assert m.body_param == "data"


def test_range_metadata():
    m = _meta("range")
    assert m.method == "GET"
    assert m.path == "/range"


def test_count_metadata():
    m = _meta("count")
    assert m.method == "GET"
    assert m.path == "/count"


def test_clear_metadata():
    m = _meta("clear")
    assert m.method == "POST"
    assert m.path == "/clear"


def test_live_is_local_only():
    assert hasattr(AsyncBeaverLog.live, "__beaver_local_only__")


def test_dump_is_local_only():
    assert hasattr(AsyncBeaverLog.dump, "__beaver_local_only__")


def test_load_is_local_only():
    assert hasattr(AsyncBeaverLog.load, "__beaver_local_only__")


def test_batched_is_local_only():
    assert hasattr(AsyncBeaverLog.batched, "__beaver_local_only__")

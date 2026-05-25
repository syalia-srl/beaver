import json
import pytest
from typer.testing import CliRunner

from beaver.cli.main import app


runner = CliRunner()


def test_cli_local_set_then_get(tmp_path):
    db_path = str(tmp_path / "x.db")
    result = runner.invoke(
        app, ["--db", db_path, "dict", "u", "set", "alice", '{"name":"Alice"}']
    )
    assert result.exit_code == 0, result.output

    result = runner.invoke(app, ["--db", db_path, "dict", "u", "get", "alice"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"name": "Alice"}


def test_cli_count_and_clear(tmp_path):
    db_path = str(tmp_path / "x.db")
    runner.invoke(app, ["--db", db_path, "dict", "u", "set", "a", '{"v":1}'])
    runner.invoke(app, ["--db", db_path, "dict", "u", "set", "b", '{"v":2}'])

    result = runner.invoke(app, ["--db", db_path, "dict", "u", "count"])
    assert result.exit_code == 0
    assert json.loads(result.output) == 2

    result = runner.invoke(app, ["--db", db_path, "dict", "u", "clear"])
    assert result.exit_code == 0

    result = runner.invoke(app, ["--db", db_path, "dict", "u", "count"])
    assert json.loads(result.output) == 0


def test_cli_get_missing_exits_nonzero(tmp_path):
    db_path = str(tmp_path / "x.db")
    result = runner.invoke(app, ["--db", db_path, "dict", "u", "get", "missing"])
    assert result.exit_code != 0


def test_cli_requires_exactly_one_source(tmp_path):
    db_path = str(tmp_path / "x.db")
    result = runner.invoke(app, ["dict", "u", "count"])
    assert result.exit_code != 0
    assert "exactly one" in result.output.lower() or "db" in result.output.lower()


def test_cli_set_value_from_stdin(tmp_path):
    db_path = str(tmp_path / "x.db")
    result = runner.invoke(
        app,
        ["--db", db_path, "dict", "u", "set", "alice", "-"],
        input='{"name":"Alice","src":"stdin"}',
    )
    assert result.exit_code == 0, result.output

    result = runner.invoke(app, ["--db", db_path, "dict", "u", "get", "alice"])
    assert json.loads(result.output) == {"name": "Alice", "src": "stdin"}


@pytest.fixture
def remote_server(tmp_path, monkeypatch):
    """Stand up an ASGI app and monkeypatch httpx.AsyncClient to use it."""
    import asyncio

    import httpx
    from httpx import ASGITransport

    from beaver.core import AsyncBeaverDB
    from beaver.server import create_app

    async def boot():
        adb = AsyncBeaverDB(str(tmp_path / "remote.db"))
        await adb.connect()
        return adb

    adb = asyncio.new_event_loop().run_until_complete(boot())
    fastapi_app = create_app(adb)
    transport = ASGITransport(app=fastapi_app)

    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs.pop("transport", None)
        original_init(self, *args, transport=transport, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)
    yield


def test_cli_remote_set_then_get(remote_server):
    result = runner.invoke(
        app, ["--url", "http://test", "dict", "u", "set", "alice", '{"name":"Alice"}']
    )
    assert result.exit_code == 0, result.output

    result = runner.invoke(app, ["--url", "http://test", "dict", "u", "get", "alice"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"name": "Alice"}

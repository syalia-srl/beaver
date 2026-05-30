import pytest
from beaver.server import create_app
from beaver.core import AsyncBeaverDB


@pytest.fixture
async def db(tmp_path):
    db = AsyncBeaverDB(str(tmp_path / "test.db"))
    await db.connect()
    yield db
    await db.close()


@pytest.mark.asyncio
async def test_router_has_all_eight_dict_routes(db):
    app = create_app(db)
    paths = {
        (r.path, tuple(sorted(r.methods))) for r in app.routes if hasattr(r, "methods")
    }
    assert ("/dicts/{name}/{key}", ("GET",)) in paths
    assert ("/dicts/{name}/{key}", ("PUT",)) in paths
    assert ("/dicts/{name}/{key}", ("DELETE",)) in paths
    assert ("/dicts/{name}/{key}/fetch", ("GET",)) in paths
    assert ("/dicts/{name}/{key}/pop", ("POST",)) in paths
    assert ("/dicts/{name}/count", ("GET",)) in paths
    assert ("/dicts/{name}/{key}/contains", ("GET",)) in paths
    assert ("/dicts/{name}/clear", ("POST",)) in paths


@pytest.mark.asyncio
async def test_router_has_all_list_routes(db):
    app = create_app(db)
    paths = {
        (r.path, tuple(sorted(r.methods))) for r in app.routes if hasattr(r, "methods")
    }
    assert ("/lists/{name}/count", ("GET",)) in paths
    assert ("/lists/{name}/item/{index}", ("GET",)) in paths
    assert ("/lists/{name}/item/{index}", ("PUT",)) in paths
    assert ("/lists/{name}/item/{index}", ("DELETE",)) in paths
    assert ("/lists/{name}/contains", ("GET",)) in paths
    assert ("/lists/{name}/push", ("POST",)) in paths
    assert ("/lists/{name}/prepend", ("POST",)) in paths
    assert ("/lists/{name}/insert/{index}", ("POST",)) in paths
    assert ("/lists/{name}/pop", ("POST",)) in paths
    assert ("/lists/{name}/deque", ("POST",)) in paths
    assert ("/lists/{name}/clear", ("POST",)) in paths


@pytest.mark.asyncio
async def test_router_has_all_queue_routes(db):
    app = create_app(db)
    paths = {
        (r.path, tuple(sorted(r.methods))) for r in app.routes if hasattr(r, "methods")
    }
    assert ("/queues/{name}/put", ("POST",)) in paths
    assert ("/queues/{name}/peek", ("GET",)) in paths
    assert ("/queues/{name}/get", ("POST",)) in paths
    assert ("/queues/{name}/count", ("GET",)) in paths
    assert ("/queues/{name}/clear", ("POST",)) in paths


@pytest.mark.asyncio
async def test_router_has_all_log_routes(db):
    app = create_app(db)
    paths = {
        (r.path, tuple(sorted(r.methods))) for r in app.routes if hasattr(r, "methods")
    }
    assert ("/logs/{name}/log", ("POST",)) in paths
    assert ("/logs/{name}/range", ("GET",)) in paths
    assert ("/logs/{name}/count", ("GET",)) in paths
    assert ("/logs/{name}/clear", ("POST",)) in paths

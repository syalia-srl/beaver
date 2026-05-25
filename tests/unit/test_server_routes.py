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
    paths = {(r.path, tuple(sorted(r.methods))) for r in app.routes if hasattr(r, "methods")}
    assert ("/dicts/{name}/{key}", ("GET",)) in paths
    assert ("/dicts/{name}/{key}", ("PUT",)) in paths
    assert ("/dicts/{name}/{key}", ("DELETE",)) in paths
    assert ("/dicts/{name}/{key}/fetch", ("GET",)) in paths
    assert ("/dicts/{name}/{key}/pop", ("POST",)) in paths
    assert ("/dicts/{name}/count", ("GET",)) in paths
    assert ("/dicts/{name}/{key}/contains", ("GET",)) in paths
    assert ("/dicts/{name}/clear", ("POST",)) in paths

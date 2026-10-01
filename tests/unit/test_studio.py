import json

import httpx
import pytest

from beaver.core import AsyncBeaverDB
from beaver.studio import create_studio_app


pytestmark = pytest.mark.unit


async def _request(app, method: str, path: str, **kwargs):
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://studio"
    ) as client:
        return await client.request(method, path, **kwargs)


@pytest.fixture
async def studio_database(tmp_path):
    path = tmp_path / "studio.db"
    db = await AsyncBeaverDB(str(path)).connect()
    await db.connection.execute(
        "INSERT INTO __beaver_dicts__ VALUES (?, ?, ?, ?)",
        ("settings", "theme", json.dumps("dark"), None),
    )
    await db.connection.execute(
        "INSERT INTO __beaver_logs__ VALUES (?, ?, ?)",
        ("audit", 1.0, json.dumps({"message": "<img src=x onerror=alert(1)>"})),
    )
    await db.docs("articles").index(
        id="studio",
        body={"title": "Studio guide", "body": "Safe local inspection"},
        fuzzy=True,
    )
    await db.vectors("embeddings").set("v1", [3.0, 4.0], metadata={"label": "A"})
    await db.graph("links").link("alice", "bob", "knows")
    await db.blob("assets").put(
        "hello.txt", b"hello world", metadata={"content_type": "text/plain"}
    )
    await db.connection.execute(
        "INSERT INTO __beaver_pubsub_log__ VALUES (?, ?, ?)",
        (2.0, "updates", json.dumps({"event": "ready"})),
    )
    await db.sketch("visitors", capacity=1000, error_rate=0.01).add("alice")
    await db.connection.execute(
        "INSERT INTO __beaver_lock_waiters__ VALUES (?, ?, ?, ?)",
        ("sync", "waiter-1", 1.0, 9_999_999_999.0),
    )
    await db.connection.execute("CREATE TABLE customer_notes (id INTEGER, note TEXT)")
    await db.connection.execute(
        "INSERT INTO __beaver_dicts__ VALUES (?, ?, ?, ?)",
        ("__metadata__", "internal", json.dumps(True), None),
    )
    await db.close()
    return path


async def test_studio_lifespan_opens_read_only_inspector_and_closes_it(
    studio_database,
):
    app = create_studio_app(studio_database)

    async with app.router.lifespan_context(app):
        assert app.state.beaver_db.read_only is True
        response = await _request(app, "GET", "/admin/v1/info")
        assert response.status_code == 200
        assert response.json()["read_only"] is True
        assert response.json()["path"] == str(studio_database)

    with pytest.raises(ConnectionError):
        app.state.beaver_db.connection


async def test_studio_catalog_and_bounded_items(studio_database):
    app = create_studio_app(studio_database)

    async with app.router.lifespan_context(app):
        catalog = await _request(app, "GET", "/admin/v1/catalog")
        internal_catalog = await _request(
            app, "GET", "/admin/v1/catalog", params={"include_internal": "true"}
        )
        page = await _request(
            app,
            "GET",
            "/admin/v1/stores/dict/items",
            params={"name": "settings", "limit": 1},
        )

    assert catalog.status_code == 200
    assert {(entry["kind"], entry["name"]) for entry in catalog.json()} == {
        ("blob", "assets"),
        ("dict", "settings"),
        ("docs", "articles"),
        ("graph", "links"),
        ("lock", "sync"),
        ("log", "audit"),
        ("channel", "updates"),
        ("sketch", "visitors"),
        ("vectors", "embeddings"),
    }
    assert page.status_code == 200
    assert page.json()["items"][0]["value"] == "dark"
    assert page.json()["total"] == 1
    assert ("dict", "__metadata__") in {
        (entry["kind"], entry["name"]) for entry in internal_catalog.json()
    }


async def test_studio_document_search_ranges_and_index_status(studio_database):
    app = create_studio_app(studio_database)

    async with app.router.lifespan_context(app):
        documents = await _request(
            app,
            "GET",
            "/admin/v1/stores/docs/items",
            params={"name": "articles", "query": "Studio?", "search": "fts"},
        )
        indexes = await _request(
            app,
            "GET",
            "/admin/v1/stores/docs/indexes",
            params={"name": "articles"},
        )
        ranged_logs = await _request(
            app,
            "GET",
            "/admin/v1/stores/log/items",
            params={"name": "audit", "start": 1.0, "end": 1.0},
        )

    assert (
        documents.status_code == indexes.status_code == ranged_logs.status_code == 200
    )
    assert documents.json()["items"][0]["id"] == "studio"
    assert indexes.json()["fts_items"] == 1
    assert indexes.json()["fuzzy_items"] == 1
    assert ranged_logs.json()["total"] == 1


async def test_studio_serves_remaining_viewers_details_and_diagnostics(
    studio_database,
):
    app = create_studio_app(studio_database)

    async with app.router.lifespan_context(app):
        vectors = await _request(
            app,
            "GET",
            "/admin/v1/stores/vectors/items",
            params={"name": "embeddings"},
        )
        vector = await _request(
            app,
            "GET",
            "/admin/v1/stores/vectors/item",
            params={"name": "embeddings", "id": "v1"},
        )
        blobs = await _request(
            app,
            "GET",
            "/admin/v1/stores/blob/items",
            params={"name": "assets"},
        )
        blob = await _request(
            app,
            "GET",
            "/admin/v1/stores/blob/item",
            params={"name": "assets", "id": "hello.txt", "preview_bytes": 5},
        )
        schema = await _request(app, "GET", "/admin/v1/schema")
        diagnostics = await _request(app, "GET", "/admin/v1/diagnostics")
        operations = await _request(app, "GET", "/admin/v1/operations")

    assert all(
        response.status_code == 200
        for response in (vectors, vector, blobs, blob, schema, diagnostics, operations)
    )
    assert "vector" not in vectors.json()["items"][0]
    assert vector.json()["vector"] == pytest.approx([3.0, 4.0])
    assert "data" not in blobs.json()["items"][0]
    assert blob.json()["preview"] == "hello"
    assert any(item["name"] == "customer_notes" for item in schema.json())
    assert diagnostics.json()["vectors"][0]["lsh_items"] == 1
    assert operations.json()


async def test_studio_errors_use_the_beaver_error_envelope(studio_database):
    app = create_studio_app(studio_database)

    async with app.router.lifespan_context(app):
        unsupported = await _request(
            app,
            "GET",
            "/admin/v1/stores/events/items",
            params={"name": "events"},
        )
        invalid_limit = await _request(
            app,
            "GET",
            "/admin/v1/stores/dict/items",
            params={"name": "settings", "limit": 201},
        )

    assert unsupported.status_code == 400
    assert unsupported.json() == {
        "error": "ValueError",
        "message": "Unsupported or not-yet-browsable store kind: 'events'.",
        "detail": None,
    }
    assert invalid_limit.status_code == 400
    assert set(invalid_limit.json()) == {"error", "message", "detail"}


async def test_studio_is_get_only_and_serves_offline_xss_safe_assets(studio_database):
    app = create_studio_app(studio_database)

    async with app.router.lifespan_context(app):
        index = await _request(app, "GET", "/")
        script = await _request(app, "GET", "/assets/app.js")
        styles = await _request(app, "GET", "/assets/app.css")
        mutation = await _request(app, "POST", "/admin/v1/catalog")

    assert index.status_code == script.status_code == styles.status_code == 200
    assert "https://" not in index.text
    assert "http://" not in index.text
    assert "textContent" in script.text
    assert "innerHTML" not in script.text
    assert "data_version" in script.text
    assert "follow" in script.text.lower()
    assert "document-search" in index.text
    assert "graph-filters" in index.text
    assert "diagnostics-output" in index.text
    assert "operations-output" in index.text
    assert "search" in script.text.lower()
    assert "preview_bytes" not in script.text
    assert mutation.status_code == 405

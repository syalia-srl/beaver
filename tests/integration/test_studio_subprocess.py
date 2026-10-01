"""End-to-end smoke test for the packaged Beaver Studio command."""

import hashlib
import socket
import subprocess
import sys
import time

import httpx
import pytest

from beaver import BeaverDB


pytestmark = pytest.mark.integration


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _digest(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_studio_subprocess_serves_catalog_without_modifying_database(tmp_path):
    path = tmp_path / "studio.db"
    with BeaverDB(str(path)) as db:
        db.dict("settings").set("theme", "dark")
        db.docs("articles").index(
            id="studio",
            body={"title": "Studio guide", "body": "Safe local inspection"},
            fuzzy=True,
        )
        db.vectors("embeddings").set("v1", [3.0, 4.0])
        db.blob("assets").put(
            "hello.txt", b"hello world", metadata={"content_type": "text/plain"}
        )
    before = _digest(path)
    port = _free_port()
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "beaver.cli.main",
            "studio",
            "--db",
            str(path),
            "--port",
            str(port),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                response = httpx.get(f"{base_url}/admin/v1/info", timeout=0.3)
                if response.status_code == 200:
                    break
            except (httpx.ConnectError, httpx.ReadTimeout):
                time.sleep(0.1)
        else:
            process.terminate()
            output, error = process.communicate(timeout=2)
            raise RuntimeError(
                "Studio failed to boot in 5s: "
                f"stdout={output.decode()} stderr={error.decode()}"
            )

        assert response.json()["read_only"] is True
        catalog = httpx.get(f"{base_url}/admin/v1/catalog", timeout=1)
        assert catalog.status_code == 200
        assert [(entry["kind"], entry["name"]) for entry in catalog.json()] == [
            ("blob", "assets"),
            ("dict", "settings"),
            ("docs", "articles"),
            ("vectors", "embeddings"),
        ]
        documents = httpx.get(
            f"{base_url}/admin/v1/stores/docs/items",
            params={"name": "articles", "query": "Studio?", "search": "fts"},
            timeout=1,
        )
        indexes = httpx.get(
            f"{base_url}/admin/v1/stores/docs/indexes",
            params={"name": "articles"},
            timeout=1,
        )
        assert documents.status_code == indexes.status_code == 200
        assert documents.json()["items"][0]["id"] == "studio"
        assert indexes.json()["fts_items"] == 1
        vector = httpx.get(
            f"{base_url}/admin/v1/stores/vectors/item",
            params={"name": "embeddings", "id": "v1"},
            timeout=1,
        )
        blob = httpx.get(
            f"{base_url}/admin/v1/stores/blob/item",
            params={"name": "assets", "id": "hello.txt", "preview_bytes": 5},
            timeout=1,
        )
        assert vector.status_code == blob.status_code == 200
        assert vector.json()["vector"] == pytest.approx([3.0, 4.0])
        assert blob.json()["preview"] == "hello"
        index = httpx.get(base_url, timeout=1)
        assert index.status_code == 200
        assert "Beaver Studio" in index.text
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)

    assert _digest(path) == before

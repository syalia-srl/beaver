"""End-to-end smoke test: boot a real uvicorn server in a subprocess and round-trip."""

import socket
import subprocess
import sys
import time

import httpx
import pytest


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def server(tmp_path):
    port = _free_port()
    db_path = str(tmp_path / "smoke.db")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "beaver.cli.main",
            "serve",
            "--db",
            db_path,
            "--port",
            str(port),
            "--host",
            "127.0.0.1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            httpx.get(f"{base_url}/openapi.json", timeout=0.3)
            break
        except (httpx.ConnectError, httpx.ReadTimeout):
            time.sleep(0.1)
    else:
        proc.terminate()
        out, err = proc.communicate(timeout=2)
        raise RuntimeError(
            f"server failed to boot in 5s: stdout={out.decode()} stderr={err.decode()}"
        )

    yield base_url

    proc.terminate()
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        proc.kill()


def test_subprocess_set_then_get(server):
    with httpx.Client(base_url=server) as c:
        r = c.put("/dicts/u/alice", json={"value": {"name": "Alice"}})
        assert r.status_code == 200
        r = c.get("/dicts/u/alice")
        assert r.status_code == 200
        assert r.json() == {"name": "Alice"}

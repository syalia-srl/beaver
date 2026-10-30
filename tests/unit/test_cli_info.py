import json

from typer.testing import CliRunner

from beaver import BeaverDB
from beaver.cli.main import app


runner = CliRunner()


def _seed_inspection_db(path):
    with BeaverDB(str(path)) as db:
        db.dict("settings").set("theme", "dark")
        db.dict("__metadata__").set("internal", True)
        db.list("tasks").push("ship")


def test_cli_info_json_lists_stores(tmp_path):
    db_path = tmp_path / "info.db"
    _seed_inspection_db(db_path)

    result = runner.invoke(app, ["info", "--db", str(db_path), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["database"]["read_only"] is True
    assert {(entry["kind"], entry["name"]) for entry in payload["stores"]} == {
        ("dict", "settings"),
        ("list", "tasks"),
    }


def test_cli_info_human_output(tmp_path):
    db_path = tmp_path / "info.db"
    _seed_inspection_db(db_path)

    result = runner.invoke(app, ["info", "--db", str(db_path)])

    assert result.exit_code == 0, result.output
    assert "Beaver database" in result.output
    assert "settings" in result.output
    assert "tasks" in result.output


def test_cli_info_can_include_internal_stores(tmp_path):
    db_path = tmp_path / "info.db"
    _seed_inspection_db(db_path)

    result = runner.invoke(
        app, ["info", "--db", str(db_path), "--json", "--include-internal"]
    )

    assert result.exit_code == 0, result.output
    stores = json.loads(result.output)["stores"]
    assert ("dict", "__metadata__") in {
        (entry["kind"], entry["name"]) for entry in stores
    }


def test_cli_info_missing_database_does_not_create_it(tmp_path):
    db_path = tmp_path / "missing.db"

    result = runner.invoke(app, ["info", "--db", str(db_path), "--json"])

    assert result.exit_code != 0
    assert not db_path.exists()


def test_cli_studio_binds_to_loopback(tmp_path, monkeypatch):
    db_path = tmp_path / "studio.db"
    _seed_inspection_db(db_path)
    called = {}

    def fake_run(app, **kwargs):
        called.update(kwargs)

    monkeypatch.setattr("uvicorn.run", fake_run)

    result = runner.invoke(app, ["studio", "--db", str(db_path), "--port", "8765"])

    assert result.exit_code == 0, result.output
    assert called == {"host": "127.0.0.1", "port": 8765}
    assert "read only" in result.output

"""Create a representative Beaver database for trying Beaver Studio."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any

from beaver import BeaverDB


DEFAULT_DATABASE = Path(__file__).with_name("studio-demo.db")


def create_demo(path: Path) -> None:
    """Populate ``path`` with small, readable examples of Beaver modalities."""
    db = BeaverDB(str(path))
    try:
        settings: Any = db.dict("settings")
        settings["theme"] = "dark"
        settings["language"] = "es"
        settings["max_retries"] = 3
        settings["features"] = {
            "studio": True,
            "semantic_search": True,
            "experimental": False,
        }
        settings["safe_rendering_example"] = "<img src=x onerror=alert('blocked')>"
        settings["oversized_example"] = {
            "description": "Studio returns a bounded preview for this value.",
            "payload": "x" * 70_000,
        }

        tasks: Any = db.list("tasks")
        tasks.push({"title": "Inspect the database", "done": True, "owner": "Ana"})
        tasks.push({"title": "Review queued jobs", "done": False, "owner": "Luis"})
        tasks.push({"title": "Follow application logs", "done": False, "owner": "Mara"})
        tasks.push({"title": "Plan the next Studio viewer", "done": False})

        jobs: Any = db.queue("jobs")
        jobs.put({"type": "generate_report", "report_id": "weekly-42"}, priority=1)
        jobs.put({"type": "send_email", "recipient": "team@example.com"}, priority=5)
        jobs.put({"type": "refresh_index", "collection": "knowledge"}, priority=3)

        events: Any = db.log("application_events")
        now = datetime.now(timezone.utc)
        events.log(
            {"level": "info", "message": "Worker started", "worker": "alpha"},
            timestamp=(now - timedelta(minutes=12)).timestamp(),
        )
        events.log(
            {"level": "info", "message": "Report generated", "duration_ms": 184},
            timestamp=(now - timedelta(minutes=8)).timestamp(),
        )
        events.log(
            {"level": "warning", "message": "Retry scheduled", "attempt": 2},
            timestamp=(now - timedelta(minutes=3)).timestamp(),
        )
        events.log(
            {"level": "info", "message": "Demo database ready"},
            timestamp=now.timestamp(),
        )

        knowledge: Any = db.docs("knowledge")
        knowledge.index(
            id="local-first",
            body="Beaver stores every modality in one standard SQLite file.",
            fuzzy=True,
        )
        knowledge.index(
            id="studio",
            body="Beaver Studio inspects a database through a read-only connection.",
            fuzzy=True,
        )

        embeddings: Any = db.vectors("article_embeddings")
        embeddings.set(
            "local-first", [0.9, 0.1, 0.2], metadata={"topic": "architecture"}
        )
        embeddings.set("studio", [0.8, 0.2, 0.4], metadata={"topic": "tooling"})

        dependencies: Any = db.graph("service_dependencies")
        dependencies.link("api", "database", "uses", metadata={"critical": True})
        dependencies.link(
            "studio", "database", "inspects", metadata={"read_only": True}
        )

        assets: Any = db.blob("assets")
        assets.put(
            "welcome.txt",
            b"Welcome to the Beaver Studio demo.\n",
            metadata={"content_type": "text/plain", "language": "en"},
        )

        visitors: Any = db.sketch("unique_visitors", capacity=10_000, error_rate=0.01)
        for visitor in ("alice", "bob", "carol", "alice"):
            visitors.add(visitor)
    finally:
        db.close()

    timestamp = now.timestamp()
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO __beaver_pubsub_log__ "
            "(timestamp, channel_name, message_payload) VALUES (?, ?, ?)",
            (
                timestamp,
                "notifications",
                json.dumps({"type": "demo", "message": "Studio data is ready"}),
            ),
        )
        connection.execute(
            "INSERT INTO __beaver_lock_waiters__ "
            "(lock_name, waiter_id, requested_at, expires_at) VALUES (?, ?, ?, ?)",
            ("report_generation", "demo-waiter", timestamp, timestamp + 3_600),
        )
        connection.execute(
            "CREATE TABLE demo_external_notes (id INTEGER PRIMARY KEY, note TEXT)"
        )
        connection.execute(
            "INSERT INTO demo_external_notes (note) VALUES (?)",
            ("This table is intentionally outside Beaver's semantic schema.",),
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DATABASE,
        help=f"destination database (default: {DEFAULT_DATABASE})",
    )
    args = parser.parse_args()
    path: Path = args.db

    if path.exists():
        parser.error(f"refusing to overwrite existing database: {path}")

    path.parent.mkdir(parents=True, exist_ok=True)
    create_demo(path)
    print(f"Created Beaver Studio demo: {path.resolve()}")
    print(f"Run: uv run beaver studio --db {path}")


if __name__ == "__main__":
    main()

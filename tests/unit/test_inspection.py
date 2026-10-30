import json
import time

import pytest

from beaver.inspection import AsyncBeaverInspector


pytestmark = pytest.mark.unit


async def test_info_reports_read_only_database(async_db, tmp_path):
    inspector = AsyncBeaverInspector(async_db)

    info = await inspector.info()

    assert info.path == async_db.path
    assert info.schema_version == 1
    assert info.beaver_version
    assert info.journal_mode.lower() == "wal"
    assert info.read_only is False
    assert info.size_bytes > 0
    assert info.data_version >= 1


async def test_catalog_discovers_every_modality_and_hides_internal(async_db):
    now = time.time()
    statements = [
        (
            "INSERT INTO __beaver_dicts__ VALUES (?, ?, ?, ?)",
            ("settings", "theme", '"dark"', None),
        ),
        (
            "INSERT INTO __beaver_dicts__ VALUES (?, ?, ?, ?)",
            ("expired", "old", "1", now - 1),
        ),
        (
            "INSERT INTO __beaver_dicts__ VALUES (?, ?, ?, ?)",
            ("__security__", "secret-dict", "{}", None),
        ),
        (
            "INSERT INTO __beaver_lists__ VALUES (?, ?, ?)",
            ("tasks", "a", '"one"'),
        ),
        (
            "INSERT INTO __beaver_priority_queues__ VALUES (?, ?, ?, ?)",
            ("jobs", 1.0, now, '{"job": 1}'),
        ),
        (
            "INSERT INTO __beaver_logs__ VALUES (?, ?, ?)",
            ("audit", now, '{"event": "start"}'),
        ),
        (
            "INSERT INTO __beaver_documents__ VALUES (?, ?, ?)",
            ("articles", "d1", '{"title": "Beaver"}'),
        ),
        (
            "INSERT INTO __beaver_vectors__ VALUES (?, ?, ?, ?)",
            ("embeddings", "v1", b"\0\0\0\0", "{}"),
        ),
        (
            "INSERT INTO __beaver_edges__ VALUES (?, ?, ?, ?, ?)",
            ("knowledge", "a", "b", "links", "{}"),
        ),
        (
            "INSERT INTO __beaver_blobs__ VALUES (?, ?, ?, ?)",
            ("assets", "logo", b"png", '{"type": "image/png"}'),
        ),
        (
            "INSERT INTO __beaver_pubsub_log__ VALUES (?, ?, ?)",
            (now, "updates", '{"ok": true}'),
        ),
        (
            "INSERT INTO __beaver_pubsub_log__ VALUES (?, ?, ?)",
            (now + 1, "__events_dict:settings__", "{}"),
        ),
        (
            "INSERT INTO __beaver_sketches__ VALUES (?, ?, ?, ?, ?)",
            ("visitors", "approximate_set", 1000, 0.01, b"data"),
        ),
        (
            "INSERT INTO __beaver_lock_waiters__ VALUES (?, ?, ?, ?)",
            ("sync", "w1", now, now + 60),
        ),
        (
            "INSERT INTO __beaver_lock_waiters__ VALUES (?, ?, ?, ?)",
            ("__internal_lock__dict__settings", "w2", now + 1, now + 60),
        ),
    ]
    for sql, params in statements:
        await async_db.connection.execute(sql, params)

    inspector = AsyncBeaverInspector(async_db)
    catalog = await inspector.catalog()
    pairs = {(entry.kind, entry.name) for entry in catalog}

    assert pairs == {
        ("dict", "settings"),
        ("dict", "expired"),
        ("list", "tasks"),
        ("queue", "jobs"),
        ("log", "audit"),
        ("docs", "articles"),
        ("vectors", "embeddings"),
        ("graph", "knowledge"),
        ("blob", "assets"),
        ("channel", "updates"),
        ("sketch", "visitors"),
        ("lock", "sync"),
    }
    by_pair = {(entry.kind, entry.name): entry for entry in catalog}
    assert by_pair[("dict", "settings")].browsable is True
    assert by_pair[("docs", "articles")].browsable is True
    assert by_pair[("sketch", "visitors")].count is None
    assert by_pair[("sketch", "visitors")].count_is_exact is False
    assert by_pair[("dict", "expired")].warnings

    internal = await inspector.catalog(include_internal=True)
    internal_pairs = {(entry.kind, entry.name) for entry in internal}
    assert ("dict", "__security__") in internal_pairs
    assert ("channel", "__events_dict:settings__") in internal_pairs
    assert ("lock", "__internal_lock__dict__settings") in internal_pairs


async def test_dict_pages_are_stable_redacted_and_localize_bad_json(async_db):
    rows = [
        ("plain", "a", json.dumps({"n": 1}), None),
        ("plain", "b", "not-json", None),
        ("plain", "c", json.dumps({"n": 3}), time.time() - 1),
        ("secret", "password", "ciphertext", None),
        ("__security__", "secret", "{}", None),
    ]
    await async_db.connection.executemany(
        "INSERT INTO __beaver_dicts__ VALUES (?, ?, ?, ?)", rows
    )
    inspector = AsyncBeaverInspector(async_db)

    first = await inspector.page("dict", "plain", limit=2)
    second = await inspector.page("dict", "plain", limit=2, cursor=first.next_cursor)

    assert [item["key"] for item in first.items] == ["a", "b"]
    assert first.items[0]["value"] == {"n": 1}
    assert first.items[1]["raw_value"] == "not-json"
    assert first.items[1]["warnings"]
    assert [item["key"] for item in second.items] == ["c"]
    assert second.items[0]["expired"] is True
    assert second.next_cursor is None

    secret = await inspector.page("dict", "secret")
    assert secret.items[0]["redacted"] is True
    assert "value" not in secret.items[0]


async def test_list_queue_and_log_pagination_is_non_destructive(async_db):
    await async_db.connection.executemany(
        "INSERT INTO __beaver_lists__ VALUES (?, ?, ?)",
        [("letters", "a", '"A"'), ("letters", "b", '"B"'), ("letters", "c", '"C"')],
    )
    await async_db.connection.executemany(
        "INSERT INTO __beaver_priority_queues__ VALUES (?, ?, ?, ?)",
        [
            ("jobs", 1.0, 10.0, '"first"'),
            ("jobs", 1.0, 10.0, '"second"'),
            ("jobs", 2.0, 11.0, '"third"'),
        ],
    )
    await async_db.connection.executemany(
        "INSERT INTO __beaver_logs__ VALUES (?, ?, ?)",
        [
            ("events", 1.0, '"one"'),
            ("events", 2.0, '"two"'),
            ("events", 3.0, '"three"'),
        ],
    )
    inspector = AsyncBeaverInspector(async_db)

    lists_1 = await inspector.page("list", "letters", limit=2)
    lists_2 = await inspector.page(
        "list", "letters", limit=2, cursor=lists_1.next_cursor
    )
    assert [item["index"] for item in lists_1.items + lists_2.items] == [0, 1, 2]
    assert [item["value"] for item in lists_1.items + lists_2.items] == ["A", "B", "C"]

    before = await async_db.queue("jobs").count()
    queues_1 = await inspector.page("queue", "jobs", limit=2)
    queues_2 = await inspector.page(
        "queue", "jobs", limit=2, cursor=queues_1.next_cursor
    )
    after = await async_db.queue("jobs").count()
    assert before == after == 3
    assert [item["data"] for item in queues_1.items + queues_2.items] == [
        "first",
        "second",
        "third",
    ]

    logs_1 = await inspector.page("log", "events", limit=2)
    logs_2 = await inspector.page("log", "events", limit=2, cursor=logs_1.next_cursor)
    assert [item["timestamp"] for item in logs_1.items + logs_2.items] == [
        1.0,
        2.0,
        3.0,
    ]


async def test_log_tail_cursor_returns_rows_appended_later(async_db):
    await async_db.connection.execute(
        "INSERT INTO __beaver_logs__ VALUES (?, ?, ?)",
        ("events", 1.0, '"first"'),
    )
    inspector = AsyncBeaverInspector(async_db)

    current = await inspector.page("log", "events")

    assert current.has_more is False
    assert current.next_cursor is not None
    empty_poll = await inspector.page("log", "events", cursor=current.next_cursor)
    assert empty_poll.items == []
    assert empty_poll.next_cursor == current.next_cursor

    await async_db.connection.execute(
        "INSERT INTO __beaver_logs__ VALUES (?, ?, ?)",
        ("events", 2.0, '"later"'),
    )

    appended = await inspector.page("log", "events", cursor=empty_poll.next_cursor)
    assert [item["data"] for item in appended.items] == ["later"]
    assert appended.has_more is False


async def test_log_page_supports_bounded_time_ranges(async_db):
    await async_db.connection.executemany(
        "INSERT INTO __beaver_logs__ VALUES (?, ?, ?)",
        [("events", float(i), json.dumps({"n": i})) for i in range(1, 6)],
    )
    inspector = AsyncBeaverInspector(async_db)

    first = await inspector.page("log", "events", limit=1, start=2.0, end=4.0)
    second = await inspector.page(
        "log",
        "events",
        limit=2,
        cursor=first.next_cursor,
        start=2.0,
        end=4.0,
    )

    assert [item["data"]["n"] for item in first.items + second.items] == [2, 3, 4]
    assert first.total == 3
    assert second.has_more is False


async def test_oversized_values_are_truncated_before_json_decoding(async_db):
    value = json.dumps({"payload": "x" * 70_000})
    await async_db.connection.execute(
        "INSERT INTO __beaver_dicts__ VALUES (?, ?, ?, ?)",
        ("large", "item", value, None),
    )
    inspector = AsyncBeaverInspector(async_db)

    page = await inspector.page("dict", "large")

    item = page.items[0]
    assert item["truncated"] is True
    assert item["value_size_bytes"] > 64_000
    assert len(item["value_preview"]) <= 2_048
    assert "value" not in item
    assert item["warnings"]


async def test_deep_and_binary_values_degrade_explicitly(async_db):
    deep: object = "leaf"
    for _ in range(40):
        deep = {"next": deep}
    await async_db.connection.executemany(
        "INSERT INTO __beaver_dicts__ VALUES (?, ?, ?, ?)",
        [
            ("unsafe", "binary", b"\xff\xfe", None),
            ("unsafe", "deep", json.dumps(deep), None),
        ],
    )
    inspector = AsyncBeaverInspector(async_db)

    page = await inspector.page("dict", "unsafe")
    by_key = {item["key"]: item for item in page.items}

    assert by_key["binary"]["value_preview_base64"] == "//4="
    assert by_key["binary"]["warnings"]
    assert by_key["deep"]["truncated"] is True
    assert "maximum JSON depth" in by_key["deep"]["warnings"][0]


async def test_document_pages_search_safely_and_report_indexes(async_db):
    docs = async_db.docs("articles")
    await docs.index(
        id="a",
        body={"title": "Local-first SQLite", "category": "architecture"},
        fuzzy=True,
    )
    await docs.index(
        id="b",
        body={"title": "Studio guide", "category": "tooling"},
        fuzzy=True,
    )
    inspector = AsyncBeaverInspector(async_db)

    first = await inspector.page("docs", "articles", limit=1)
    second = await inspector.page("docs", "articles", limit=1, cursor=first.next_cursor)
    fts = await inspector.page("docs", "articles", query="local-first?", search="fts")
    fuzzy = await inspector.page("docs", "articles", query="Stdio", search="fuzzy")
    indexes = await inspector.indexes("docs", "articles")

    assert [item["id"] for item in first.items + second.items] == ["a", "b"]
    assert [item["id"] for item in fts.items] == ["a"]
    assert [item["id"] for item in fuzzy.items] == ["b"]
    assert fts.total is None and fts.total_is_exact is False
    assert indexes.items == 2
    assert indexes.fts_items == 2
    assert indexes.fuzzy_items == 2
    assert indexes.field_indexes == []


async def test_document_page_localizes_malformed_json(async_db):
    await async_db.connection.execute(
        "INSERT INTO __beaver_documents__ VALUES (?, ?, ?)",
        ("broken", "bad", "not-json"),
    )
    inspector = AsyncBeaverInspector(async_db)

    page = await inspector.page("docs", "broken")

    assert page.items[0]["raw_body"] == "not-json"
    assert page.items[0]["warnings"]


async def test_document_search_and_log_range_validate_bounds(async_db):
    inspector = AsyncBeaverInspector(async_db)

    with pytest.raises(ValueError, match="at most"):
        await inspector.page("docs", "articles", query="x" * 257, search="fts")
    with pytest.raises(ValueError, match="start"):
        await inspector.page("log", "events", start=2.0, end=1.0)


async def test_remaining_modality_pages_are_bounded_and_semantic(async_db):
    now = time.time()
    await async_db.vectors("embeddings").set(
        "v1", [3.0, 4.0], metadata={"label": "demo"}
    )
    await async_db.graph("links").link(
        "alice", "bob", "knows", metadata={"since": 2024}
    )
    await async_db.blob("assets").put(
        "hello.txt", b"hello world", metadata={"content_type": "text/plain"}
    )
    await async_db.connection.execute(
        "INSERT INTO __beaver_pubsub_log__ VALUES (?, ?, ?)",
        (now, "updates", json.dumps({"event": "ready"})),
    )
    await async_db.sketch("visitors", capacity=1000, error_rate=0.01).add("alice")
    await async_db.connection.execute(
        "INSERT INTO __beaver_lock_waiters__ VALUES (?, ?, ?, ?)",
        ("sync", "waiter-1", now - 2, now + 30),
    )
    inspector = AsyncBeaverInspector(async_db)

    catalog = {(entry.kind, entry.name): entry for entry in await inspector.catalog()}
    vectors = await inspector.page("vectors", "embeddings")
    graph = await inspector.page("graph", "links", source="alice")
    blobs = await inspector.page("blob", "assets")
    channels = await inspector.page("channel", "updates")
    sketches = await inspector.page("sketch", "visitors")
    locks = await inspector.page("lock", "sync")

    assert all(
        catalog[pair].browsable
        for pair in {
            ("vectors", "embeddings"),
            ("graph", "links"),
            ("blob", "assets"),
            ("channel", "updates"),
            ("sketch", "visitors"),
            ("lock", "sync"),
        }
    )
    assert vectors.items[0]["dimension"] == 2
    assert vectors.items[0]["norm"] == pytest.approx(5.0)
    assert "vector" not in vectors.items[0]
    assert graph.items[0]["target"] == "bob"
    assert blobs.items[0]["size_bytes"] == 11
    assert "data" not in blobs.items[0]
    assert channels.items[0]["payload"] == {"event": "ready"}
    assert sketches.items[0]["approximate_count"] == 1
    assert locks.items[0]["waiter_id"] == "waiter-1"
    assert locks.items[0]["expired"] is False


async def test_vector_and_blob_details_are_explicit_and_bounded(async_db):
    await async_db.vectors("embeddings").set("v1", [1.0, 2.0, 3.0])
    await async_db.blob("assets").put(
        "large.txt",
        b"abcdef" * 20_000,
        metadata={"content_type": "text/plain"},
    )
    inspector = AsyncBeaverInspector(async_db)

    vector = await inspector.detail("vectors", "embeddings", "v1")
    blob = await inspector.detail("blob", "assets", "large.txt", preview_bytes=32)

    assert vector["vector"] == pytest.approx([1.0, 2.0, 3.0])
    assert vector["truncated"] is False
    assert blob["preview"] == "abcdefabcdefabcdefabcdefabcdefab"
    assert blob["encoding"] == "utf-8"
    assert blob["truncated"] is True
    assert blob["size_bytes"] == 120_000


async def test_graph_filters_and_channel_cursor_preserve_scope(async_db):
    await async_db.connection.executemany(
        "INSERT INTO __beaver_edges__ VALUES (?, ?, ?, ?, ?)",
        [
            ("g", "a", "b", "friend", None),
            ("g", "a", "c", "works_with", None),
            ("g", "d", "a", "friend", None),
        ],
    )
    await async_db.connection.executemany(
        "INSERT INTO __beaver_pubsub_log__ VALUES (?, ?, ?)",
        [(1.0, "events", '"one"'), (2.0, "events", '"two"')],
    )
    inspector = AsyncBeaverInspector(async_db)

    graph = await inspector.page("graph", "g", source="a", label="friend")
    first = await inspector.page("channel", "events", limit=1)
    second = await inspector.page(
        "channel", "events", limit=1, cursor=first.next_cursor
    )

    assert [(item["source"], item["target"]) for item in graph.items] == [("a", "b")]
    assert [item["payload"] for item in first.items + second.items] == ["one", "two"]


async def test_external_schema_and_index_diagnostics_are_read_only(async_db):
    await async_db.connection.execute(
        "CREATE TABLE customer_notes (id INTEGER PRIMARY KEY, note TEXT)"
    )
    await async_db.vectors("embeddings").set("v1", [1.0, 0.0])
    inspector = AsyncBeaverInspector(async_db)

    schema = await inspector.schema()
    diagnostics = await inspector.diagnostics()

    customer = next(item for item in schema if item["name"] == "customer_notes")
    assert [column["name"] for column in customer["columns"]] == ["id", "note"]
    assert not any(item["name"].startswith("__beaver_") for item in schema)
    assert diagnostics["vectors"][0]["name"] == "embeddings"
    assert diagnostics["vectors"][0]["lsh_items"] == 1


@pytest.mark.parametrize("limit", [0, -1, 51, 201])
async def test_page_rejects_invalid_limits(async_db, limit):
    inspector = AsyncBeaverInspector(async_db)

    with pytest.raises(ValueError, match="limit"):
        await inspector.page("dict", "x", limit=limit)


async def test_page_rejects_unknown_kind_and_bad_cursor(async_db):
    inspector = AsyncBeaverInspector(async_db)

    with pytest.raises(ValueError, match="Unsupported"):
        await inspector.page("table", "x")
    with pytest.raises(ValueError, match="cursor"):
        await inspector.page("dict", "x", cursor="tampered")

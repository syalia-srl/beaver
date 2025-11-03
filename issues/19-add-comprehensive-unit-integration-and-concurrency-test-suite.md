---
number: 19
title: "Add comprehensive unit, integration, and concurrency test suite"
state: open
labels:
---

### 1. Justification

The `beaver-db` library is approaching feature-completeness, with a robust set of features for data management, concurrency, and search. The design document's roadmap explicitly lists **"Comprehensive Unit Testing"** as the primary focus for the near future to ensure stability and usability.

This test suite is critical for:
* **Validating Atomic Operations:** Ensuring that low-level "read-modify-write" operations are truly atomic and free of race conditions, as planned in Issue #17.
* **Testing Concurrency:** Validating the multi-process safety of key features, especially the `LockManager`, manager-level locks, and the new `NumpyVectorIndex` synchronization.
* **Preventing Regressions:** Creating a safety net to catch bugs as new features (like the `BeaverClient` or `.load()` methods) are implemented.
* **Verifying API Contracts:** Ensuring all data managers (`dict`, `list`, `queue`, etc.) and their async wrappers (`.as_async()`) behave as documented.

### 2. Core Test Strategy

We will structure the tests into four main categories, located in a new top-level `tests/` directory.

1.  **Unit Tests (`tests/unit/`):**
    * Fast, isolated tests for individual manager methods (e.g., `ListManager.push`).
    * These tests will mock database connections where appropriate and focus on pure business logic (e.g., data serialization, FTS query building).

2.  **Integration Tests (`tests/integration/`):**
    * Tests that require a real, live database file.
    * These tests will verify the interaction between components (e.g., testing `CollectionManager.index` correctly writes to `beaver_collections` and `_vector_change_log`).
    * This is where we will test `async` wrappers, real-time `live`/`subscribe` features, and `dump()` methods.

3.  **Concurrency Tests (`tests/concurrency/`):**
    * The most critical tests for validating the "multi-process-safe" promise.
    * These tests will use Python's `multiprocessing` module (and `pytest-xdist` if needed) to spawn multiple, independent processes that all operate on the same database file simultaneously.

4.  **API/CLI Tests (`tests/api/`):**
    * Tests for the public-facing `beaver serve` REST API and the `beaver` CLI.
    * These will use `httpx` to test the server and `typer.testing.CliRunner` to test the CLI commands.

### 3. Test Setup & Tooling

* **Framework:** `pytest`
* **Async:** `pytest-asyncio`
* **Fixtures:** A core `pytest` fixture (`db`) will be created to provide a `BeaverDB` instance pointed at a temporary, unique database file for each test, ensuring tests are isolated.
* **Concurrency:** `multiprocessing` for spawning processes. `pytest-timeout` to catch deadlocks.
* **API/CLI:** `httpx` for API testing, `typer.testing.CliRunner` for CLI testing.

### 4. Detailed Test Plan

Here is a checklist of test cases to be implemented.

#### Phase 1: Unit Tests (Atomic Operations)

* **`DictManager`:**
    * [x] `test_dict_set_get`: `d["k"] = "v"`, assert `d["k"] == "v"`.
    * [x] `test_dict_del`: `del d["k"]`, assert `KeyError`.
    * [x] `test_dict_ttl`: `d.set("k", "v", ttl_seconds=1)`, `sleep(1.1)`, assert `d.get("k") is None`.
    * [x] `test_dict_len`: Assert `len(d)` is correct after adds/dels.
* **`ListManager`:**
    * [x] `test_list_push_pop`: `l.push(1)`, `l.push(2)`, assert `l.pop() == 2`, assert `l.pop() == 1`.
    * [x] `test_list_prepend_deque`: `l.prepend(1)`, `l.prepend(2)`, assert `l.deque() == 2`, assert `l.deque() == 1`.
    * [x] `test_list_indexing`: `l[0] = "new"`, assert `l[0] == "new"`.
    * [x] `test_list_slicing`: `l.push(1)`, `l.push(2)`, `l.push(3)`, assert `l[0:2] == [1, 2]`.
    * [x] `test_list_del_index`: `del l[0]`, assert `l[0] == 2`.
* **`QueueManager`:**
    * [x] `test_queue_priority`: `q.put(10, priority=10)`, `q.put(1, priority=1)`, assert `q.peek().data == 1`.
    * [x] `test_queue_fifo`: `q.put(1, priority=1)`, `q.put(2, priority=1)`, assert `q.get().data == 1`, assert `q.get().data == 2`.
    * [x] `test_queue_get_nonblocking_empty`: Assert `q.get(block=False)` raises `IndexError`.
* **`BlobManager`:**
    * [x] `test_blob_put_get_del`: `b.put("k", b"data")`, assert `b.get("k").data == b"data"`, `b.delete("k")`.
    * [x] `test_blob_metadata`: `b.put("k", b"d", metadata={"m": 1})`, assert `b.get("k").metadata == {"m": 1}`.
    * [x] `test_blob_contains`: `b.put("k", b"d")`, assert `"k" in b`.
* **`LogManager`:**
    * [ ] `test_log_log`: `logs.log(data)`, check `logs.range(...)` finds it.
    * [ ] `test_log_range`: `logs.log(...)` multiple, check `logs.range(start, end)` returns correct subset.
    * [ ] `test_log_model`: Test with `model=...` works.
    * [ ] `test_log_dump`: Test `.dump()` method.
* **`ChannelManager`:**
    * [ ] `test_channel_publish`: `c.publish(data)`, check `beaver_pubsub_log` table.
    * [ ] `test_channel_model`: Test with `model=...` works (serialization).
    * [ ] `test_channel_prune`: `c.publish(...)`, `c.prune()`, check log is empty.
* **`CollectionManager (Core)`:**
    * [x] `test_collection_index_upsert`: `c.index(doc1)`, `c.index(doc1_updated)`, assert `len(c) == 1`.
    * [x] `test_collection_drop`: `c.index(doc1)`, `c.drop(doc1)`, assert `len(c) == 0`.
* **`CollectionManager (Search/Graph)`:**
    * [x] `test_vector_search`: `c.index(vec_doc)`, `c.search(...)` returns correct doc.
    * [x] `test_fts_match`: Test `c.match("query")` returns correct doc.
    * [x] `test_fts_match_on_field`: Test `c.match("query", on=["field.path"])`.
    * [x] `test_fuzzy_match`: Test `c.match("qury", fuzziness=1)` returns doc.
    * [x] `test_graph_connect_neighbors`: `c.connect(d1, d2, "L")`, assert `d2 in c.neighbors(d1, "L")`.
    * [x] `test_graph_walk`: Test `c.walk(d1, ["L"], depth=2)` returns correct multi-hop neighbors.
* **`VectorIndex (NumpyVectorIndex)`:**
    * [ ] `test_vector_index_add`: `v.index(vec1, "id1")`, assert `v.delta_size == 1`.
    * [ ] `test_vector_drop`: `v.drop("id1")`, assert `"id1" in v._deleted_ids`.
    * [ ] `test_vector_search_correctness`: `v.index(vec1, "id1")`, `v.index(vec2, "id2")`, assert `v.search(vec1, 1)[0][0] == "id1"`.

#### Phase 2: Integration Tests (Multi-Step & Async)

* **Type Safety (`model=...`):**
    * [x] `test_model_serialization_dict`: `db.dict("d", model=Person).set("k", Person(...))`, assert `isinstance(db.dict("d", model=Person).get("k"), Person)`.
    * [x] `test_model_serialization_list`: Repeat for `list`.
    * [x] `test_model_serialization_queue`: Repeat for `queue`.
    * [x] `test_model_serialization_blob`: Repeat for `blob`.
    * [ ] `test_model_serialization_log`: Repeat for `log`.
    * [ ] `test_model_serialization_channel`: Repeat for `channel`.
* **Async Wrappers (`.as_async()`):**
    * [ ] `test_async_dict_get`: `await db.dict("d").as_async().set(...)`, `await db.dict("d").as_async().get(...)`.
    * [ ] `test_async_collection_search`: `await db.collection("c").as_async().index(...)`, `await db.collection("c").as_async().search(...)`.
* **Real-time Features:**
    * [ ] `test_queue_blocking_get`: Start `q.get(block=True)` in a thread, `q.put()` in main thread, assert `get()` receives item.
    * [x] `test_queue_blocking_timeout`: Assert `q.get(block=True, timeout=0.1)` raises `TimeoutError`.
    * [ ] `test_channel_subscribe`: Start `listener.listen()` in a thread, `c.publish()` in main thread, assert listener receives message.
    * [ ] `test_log_live`: Start `log.live()` in a thread, `log.log()` in main thread, assert `live()` yields aggregated data.
* **Data Export (`.dump()`):**
    * [x] `test_dump_dict`: For `DictManager`, call `.dump()`, assert the output JSON matches the documented structure.
    * [x] `test_dump_list`: Repeat for `ListManager`.
    * [x] `test_dump_queue`: Repeat for `QueueManager`.
    * [x] `test_dump_blob`: Repeat for `BlobManager`.
    * [ ] `test_dump_log`: Repeat for `LogManager`.
    * [ ] `test_dump_collection`: Repeat for `CollectionManager`.
* **`NumpyVectorIndex` (Compaction):**
    * [ ] `test_vector_compaction`: `c.index(doc1)`, `c.drop(doc2)`, `c.compact()`, assert `v._local_base_version` increments and `v.delta_size == 0`.

#### Phase 3: Concurrency & Multi-Process Tests

* **`LockManager` (`db.lock()`):**
    * [ ] `test_lock_mutual_exclusion`: Spawn 2 processes. P1 acquires lock, `sleep(1)`. P2 *must* block and `TimeoutError` on `db.lock("name", timeout=0.2)`.
    * [ ] `test_lock_ttl`: P1 acquires lock and `sys.exit(1)` (crashes). P2 *must* acquire the lock after `lock_ttl` seconds.
    * [ ] `test_lock_renew`: P1 acquires lock, `sleep(ttl * 0.7)`, `lock.renew()`, `sleep(ttl * 0.7)`. P2 *must not* acquire the lock during this time.
* **Manager Locks (`with db.queue(...)`):**
    * [ ] `test_atomic_batch_queue`: Pre-fill queue with 10 items. Spawn 2 processes. Each process runs `with db.queue("q") as q: ...` and calls `q.get()` 5 times. **Assert:** Both processes succeed, and total items processed is 10.
* **Internal Locks (Issue #17):**
    * [ ] `test_atomic_read_modify_write`: Pre-fill queue with 100 items. Spawn 5 processes. All processes call `queue.get()` in a tight loop (without a manager lock). **Assert:** Total successful `get()` calls across all processes is 100. (Validates `_get_item_atomically`'s internal lock).
    * [ ] `test_atomic_list_pop`: Repeat the above test for `list.pop()`.
* **`NumpyVectorIndex` Sync (Bulky Process):**
    * [ ] `test_multi_process_delta_sync`:
        * P1: `db.collection("c").search(...)` (initializes index, `_last_seen_log_id = 0`).
        * P2: `db.collection("c").index(doc1)`.
        * P1: `db.collection("c").search(...)` **Assert:** P1's `_check_and_sync()` runs, calls `_sync_deltas()`, and finds `doc1`.
    * [ ] `test_multi_process_compaction_sync`:
        * P1: `db.collection("c").search(...)` (initializes, `_local_base_version = 0`).
        * P2: `db.collection("c").compact()`.
        * P1: `db.collection("c").search(...)` **Assert:** P1's `_check_and_sync()` runs, sees `base_version = 1`, and triggers `_load_base_index()`.

#### Phase 4: API & CLI Tests

* **REST API (`beaver.server`):**
    * [ ] `test_api_all_endpoints`: For every endpoint in `beaver/server.py`, spin up the server and use `httpx` to send a valid request and assert a `200` response.
    * [ ] `test_api_404s`: Test `GET /dicts/foo/non_existent_key` returns a 404.
    * [ ] `test_api_websocket_channel`: Test `ws_connect("/channels/c/subscribe")`, `POST /channels/c/publish`, assert message received on websocket.
* **CLI (`beaver.cli`):**
    * [ ] `test_cli_all_commands`: Use `CliRunner` to invoke every CLI command (e.g., `beaver dict my-dict get my-key`) and check `result.exit_code == 0`.
    * [ ] `test_cli_lock_run`: Test `beaver lock my-lock run echo "hello"` runs successfully.
    * [ ] `test_cli_interactive`: Test `beaver channel ... listen` and `beaver log ... watch` (will require mocking/patching the live loops).
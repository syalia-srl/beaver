# beaver v2.0 — current status

> **Historical inventory:** this document was last refreshed during the v2.0
> release cycle and is stale relative to beaver 2.4.1. The tables below are
> retained as a record of that cycle; do not use them as the current feature
> matrix.

## Current branch work (2.4.1)

Issue #45 adds the Beaver Studio MVP: a local, read-only database inspector with
semantic catalog and overview views, bounded browsing for dictionaries, lists,
queues, logs, documents, vectors, graphs, blobs, channels, sketches, and locks,
plus `beaver info --db app.db` for terminal inspection. Document views include
safe FTS/fuzzy search and index coverage; payload-heavy modalities use explicit
bounded details; logs and channels support time ranges; external schema, index
health, and in-memory Studio operations are visible. Oversized, deeply nested,
binary, encrypted, or malformed values degrade explicitly. This work is in
progress on the Studio branch and is not represented in the historical tables
below.

Living inventory of what's real vs missing through the v2.0 release cycle.
Deletes itself at `2.0.0`. Last refreshed: 2026-05-30 (slice 3 of #36 landed:
`AsyncBeaverLog` joins the SID surface — `@expose` on log/range/count/clear,
`@local_only` on live/dump/load/batched, `RemoteLog`, CLI group `log`;
nested NamedTuple serialization for `range()` returning `list[LogEntry]`;
265 tests green).

Full release plan: `vault/Atlas/Architecture/2026-05-15-beaver-v2-release-plan.md` in the workspace.

## Engine — Phase 1 of design doc

| Feature | Status | Notes |
|---|---|---|
| Async-first core (`AsyncBeaverDB`) | ✅ | `core.py` owns the single `aiosqlite` connection + transaction reentrancy |
| Sync facade (`BeaverDB`) | ✅ | Reactor Thread + `BeaverBridge` (Portal Pattern) |
| All `IBeaver*` protocols | ✅ | `interfaces.py` (619 LOC) defines the SID surface |
| Pub/Sub on asyncio primitives | ✅ | `channels.py` |
| Locks via async polling | ✅ | `locks.py` |

## High-perf features — Phase 2

| Feature | Issue | Status | Notes |
|---|---|---|---|
| LSH hybrid vector search | #24 | ⚠️ wired, low recall on small/uniform data | Schema in core.py, `_ensure_lsh_hyperplanes` + `near(method="lsh")` work. **Smoke (2k random unit vectors, k=10): exact=10 results 13.7ms; lsh=1 result 3.8ms; overlap=1/10.** Worth tuning before 2.0; may be expected on small N below the documented 10k crossover. |
| `.batched()` API | #27 | ✅ on 6/7 managers | dict, list, log, blob, docs, sketch. Queues excluded per #27 §5 (batch consumption is `acquire()`'s job). Each batch buffers writes and flushes via one `executemany` per table inside one transaction. |
| Probabilistic sketches | #30 | ✅ | `ApproximateSet` (HLL + Bloom packed). **Smoke (10k items): 0.9% cardinality error; membership round-trips correctly.** |

## Stability + client parity — Phase 3

| Feature | Issue | Status | Notes |
|---|---|---|---|
| `.dump()` coverage | #18 | ✅ on six primary managers | dict, list, queue, blob, log, docs. vectors/channels/sketches/graphs/events out of scope for 2.0. |
| `.load()` coverage | #18 | ✅ JSON on six primary managers | dict, list, queue, blob, log, docs. Symmetric to `.dump()`. Strategies: `overwrite` (default, clears first) / `append`. Blob requires `payload=True` dumps. |
| JSONL streaming dump+load | #18 | ✅ on six primary managers | Both directions stream; dump via async generator, load line-by-line. Blob JSONL always carries the payload. Smoke: 1k log entries round-trip. |
| YAML dump+load | #18 | ⏸ deferred to 2.1 | JSON + JSONL satisfy the ETL story; YAML is a human-readable nicety, parked unless requested. |
| HNSW vector strategy | #28 | ⏸ deferred indefinitely | Numpy-only constraint: no `hnswlib` / `faiss` / compiled-wheel deps. Unfreezes only if/when we design a pure-numpy ANN beating LSH on >100k. Linear + LSH are the only vector strategies 2.0 ships. |
| SID consumers (CLI / Server / Client) | #36 | ✅ slice 3 (dict + list + queue + log) | Slice 1: 8 dict methods. Slice 2: generalized `_router_for_manager` with path-param coercion (`int`, `float`, `Union[int, slice]`); NamedTuple results serialized as dicts; 11 list + 5 queue methods. Slice 3: 4 log methods (log/range/count/clear), recursive NamedTuple serialization for `range()` returning `list[LogEntry]`. Round-trip end-to-end via CLI `beaver {dict,list,queue,log} ...`. Remaining managers: blob, docs, sketch, vectors, channels, graphs, events. |
| CLI admin commands | #15 | ❌ none | Layered on top of #36. Phase 2 work. |
| Concurrency tests | #19 Phase 3 | ✅ | `tests/concurrency/` covers cross-process lock mutual exclusion, list-push contention, log reader/writer race, and `.batched()` transactional isolation. 4 tests, ~16s wall-clock. `make test-concurrency` runs the suite. |
| API/CLI tests | #19 Phase 4 | ❌ none | Blocked on #36. Phase 2 work. |

## Test suite

| Metric | Value |
|---|---|
| Unit tests | 259 passing |
| Integration tests | 2 passing (`test_sync.py`, `test_server_subprocess.py`) |
| Concurrency tests | 4 passing (`tests/concurrency/`) |
| Total coverage | 88% |
| Wall-clock (`make ci`) | ~26s after deps cached |
| Wall-clock (`make test-all`) | ~44s |
| Known warning | 1 — unraisable exception (event loop closed) in pubsub teardown; cosmetic |

## Build + ops

| Item | Status |
|---|---|
| `make ci` (format-check + unit tests) | ✅ green |
| `make test-all` (format-check + unit + integration + concurrency) | ✅ green |
| `make test-concurrency` (concurrency only) | ✅ green (~16s) |
| `make sync` | ✅ |
| `pytest-timeout` (default 30s/test) | ✅ |
| GitHub Actions CI on push/PR | ✅ |
| `pyproject.toml` `beaver` script entry | dropped in Phase 0 (re-added in Phase 2 with #36) |
| Optional extras `[security]`, `[remote]` | declared, install OK |
| `[hnsw]` extra | not yet declared |
| `[yaml]` extra | not yet declared |

## README + docs honesty

| Doc | Honest? | Notes |
|---|---|---|
| `README.md` | ✅ as of Phase 0 | Quickstart now uses real API (`db.docs(...)`, `articles.search(...)`); banner notes CLI/server/Docker land in 2.0 final |
| `docs/guide-deployment.md` | ⚠️ marked | Banner at top notes "landing in 2.0 final"; body still describes the intended end-state |
| `docs/guide-collections.md` | not yet audited | TBD Phase 3 |
| Other `docs/guide-*.md` | not yet audited | TBD Phase 3 |

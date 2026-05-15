# beaver v2.0 — current status

Living inventory of what's real vs missing through the v2.0 release cycle.
Deletes itself at `2.0.0`. Last refreshed: 2026-05-15 (Phase 1 slice 4:
`.batched()` API on dict, list, log, blob, docs — sketches already had it).

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
| SID consumers (CLI / Server / Client) | #36 | ❌ none | No `@expose`, no `cli.py`, no `server.py`, no `client.py`. Phase 2 work. |
| CLI admin commands | #15 | ❌ none | Layered on top of #36. Phase 2 work. |
| Concurrency tests | #19 Phase 3 | ❌ none | `tests/concurrency/` directory does not exist. Phase 1 work. |
| API/CLI tests | #19 Phase 4 | ❌ none | Blocked on #36. Phase 2 work. |

## Test suite

| Metric | Value |
|---|---|
| Unit tests | 96 passing |
| Integration tests | 1 passing (`test_sync.py`) |
| Total coverage | 81% |
| Wall-clock (`make ci`) | ~7s after deps cached |
| Known warning | 1 — unraisable exception (event loop closed) in pubsub teardown; cosmetic |

## Build + ops

| Item | Status |
|---|---|
| `make ci` (format-check + tests) | ✅ green |
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

---
number: 38
title: "v2.0 release: Phase 1 — storage-engine layer"
state: open
labels:
- release
- 2.0
---

Phase 1 of the v2.0 release plan. Storage-engine layer: complete the ETL story,
the bulk-write API, the second vector strategy, and the concurrency tests.

Full plan: `vault/Atlas/Architecture/2026-05-15-beaver-v2-release-plan.md`.

Time-box: ~7 days. Exit condition: `2.0rc4` tag-able; STATUS.md storage-engine
rows all green; `make ci` green; coverage ≥80%.

Phase 0 (issue #37) closed `make ci` baseline + repo honesty. This phase ships
the user-visible storage features that 2.0 promises.

## 1. Complete `.load()` and `.dump()` coverage (issue #18)

Six managers in scope: **dict, list, queue, blob, log, docs**. Five have
`.dump()`; only docs is missing. None have `.load()`.

Slice order (each slice = own commit, TDD):

- [ ] **Slice 1: `.dump()` for docs.** Mirror the existing dict/list shape:
  `{metadata: {type, name, count, ...}, items: [{id, body}]}`. Write
  `test_docs_dump` first.
- [ ] **Slice 2: `.load()` JSON for all six managers + matching tests.**
  Symmetric to `.dump()`. Default `strategy="overwrite"` calls `self.clear()`
  first; `strategy="append"` skips the clear. Use the `_load_item` helper
  shape from #18 §3.C. JSON-only — no JSONL or YAML yet.
- [ ] **Slice 3: JSONL streaming dump+load.** Both directions stream
  line-by-line per #18 §3.C. Add a 10 MB streaming round-trip test that
  asserts peak memory stays bounded (e.g. via `tracemalloc` or simple
  resident-set check) — JSONL's whole point is bounded memory.
- [ ] **Slice 4: YAML extra (optional).** Defer to 2.1 unless Alex requests
  it during Phase 1. JSON + JSONL already satisfies the ETL story.

Acceptance: STATUS.md `.dump() coverage`, `.load() coverage`, `YAML / JSONL
streaming dump+load` rows all flip to ✅ (modulo YAML's deferral).

## 2. `.batched()` API on the six managers (issue #27)

Already on `sketch`. Missing on **dict, list, queue, blob, log, docs** — all
six other managers per #27 spec.

Slice approach: do `dict` first as the reference implementation (it's the
simplest), validate the context-manager + single-transaction semantics, then
fan out to the other five with parallel commits.

- [ ] Reference implementation on `AsyncBeaverDict` + `test_dict_batched`.
- [ ] Mirror onto `list`, `queue`, `blob`, `log`, `docs`. Each gets its own
  commit and `test_<manager>_batched`.
- [ ] Smoke test in `tests/integration/` — bulk-insert 10k items into each
  manager under `.batched()`, assert single-transaction (e.g. via
  `connection.total_changes` delta) and correctness.

Acceptance: STATUS.md `.batched() API` row flips to ✅ on all 7 managers.

## 3. ~~HNSW optional vector strategy~~ — dropped (2026-05-15)

Removed from Phase 1 scope. The `hnswlib`-backed approach is rejected:
beaver's vector indexing is numpy-only going forward (no compiled-wheel
deps). Issue #28 stays open as a placeholder for a future pure-numpy
ANN strategy. See [[28-add-hnsw-vector-strategy-beaver-dbhnsw]] for the
deferral reasoning.

Linear (default) + LSH (#24, optional) are the only vector strategies
2.0 ships. STATUS.md row reads "deferred — numpy-only constraint".

## 4. Concurrency test suite (issue #19 Phase 3)

`tests/concurrency/` does not exist yet. The goal: prove the Portal Pattern
and per-manager atomicity hold under real multi-process load.

- [ ] Create `tests/concurrency/` directory with `pytest.ini` marker
  `concurrency` (excluded from `make test-unit`, included in
  `make test-all`).
- [ ] Multi-process writer test: N processes each call `.set()` /
  `.push()` / `.put()` on the same manager for fixed duration; assert no
  data loss + final count matches expected.
- [ ] Reader/writer race test: writer process appends to a log/queue;
  reader process iterates concurrently; assert reader sees a monotonically
  growing view and no torn rows.
- [ ] `.batched()` isolation test: process A inside a batched block,
  process B making writes outside; assert process B's writes don't appear
  inside A's transaction.
- [ ] Wire `make test-concurrency` target; add to `make test-all` (but
  not to `make ci` — too slow for the per-push gate).

Acceptance: STATUS.md `Concurrency tests` row flips to ✅;
`make test-concurrency` runs green locally in <60 s.

## 5. Carry-over from #19 Phase 2

Three items the audit caught but Phase 0 didn't address:

- [ ] Model serialization for `log` and `channel` managers (Pydantic
  round-trip via `model_dump_json` mirroring dict/list/queue).
- [ ] Async wrappers — confirm every public method on every manager has
  an `async def` form and the sync facade goes through the Portal. Likely
  already true; needs an audit pass.
- [ ] `.dump()` for `log` and `collection` — wait, log has it. Verify
  collection (docs) covers what #19 meant by "collection" or note the
  discrepancy.

These slot in opportunistically alongside the four big deliverables — none
of them are big enough to need their own slice plan.

## Exit checklist

Phase 1 is done when:

- [ ] STATUS.md storage-engine rows all green (or ⚠️ with documented caveat
  for LSH if we don't tune it this phase).
- [ ] `make ci` green; coverage ≥80% (spot-check after each slice).
- [ ] `make test-all` green (including new integration + concurrency suites).
- [ ] `2.0rc4` tag-able. (Don't tag without Alex's go-ahead.)
- [ ] Phase 2 tracker (issue #39 — SID consumers + admin CLI) opened.

Once these tick, Phase 1 closes and we move to Phase 2.

---
number: 37
title: "v2.0 release: Phase 0 — audit and stabilize"
state: open
labels:
- release
- 2.0
---

Phase 0 of the v2.0 release plan. Foundation pass: know what's real, fix what's broken, stop lying in the README.

Full plan: `vault/Atlas/Architecture/2026-05-15-beaver-v2-release-plan.md`.

Time-box: ~3 days. Exit condition: all claims in the repo are true; tests run green in <60 s.

## 1. Inventory pass

Walk every module under `beaver/` and confirm which design-doc features are real, half-built, or absent. Capture findings somewhere durable (commit to the issue, or a top-level `STATUS.md` we delete at release time).

Specifically reconcile against design doc §3 (Architecture & Core Components) and §4 (Roadmap):

- [ ] Async-first core (`core.py`, `bridge.py`) — verify Portal Pattern is correctly wiring `BeaverDB` → reactor thread → `AsyncBeaverDB`.
- [ ] All managers ship the protocol surface declared in `interfaces.py`.
- [ ] Pub/sub (`channels.py`) uses `asyncio` primitives, not threads.
- [ ] Locks (`locks.py`) use `await asyncio.sleep()` polling, not threads.

## 2. Smoke-test the silent claims

These exist as source files but I haven't verified they work end-to-end. For each, write a 10-line script that exercises the headline use case + a unit test if missing:

- [ ] **#24 LSH hybrid vector search.** `AsyncBeaverVectors.near(method="lsh"|"auto")` returns sensible results on a 50k-vector dataset; `auto` mode crosses over from linear to LSH at the documented threshold.
- [ ] **#27 `.batched()` API.** Bulk insert 10k items into a dict / list / collection / log / blob batch; verify single-transaction semantics and correctness.
- [ ] **#30 probabilistic sketches.** `ApproximateSet` cardinality + membership against a known stream; verify HLL + Bloom packed into a single blob.

## 3. Fix the test runner

`pytest tests/unit` did not finish in 90 s on 2026-05-15. Diagnose:

- [ ] `tests/benchmark_lsh.py` and `tests/perftest.py` sit alongside `tests/unit/` — confirm whether they're collected by the unit run despite `testpaths = tests`. If yes, move them to `tests/perf/` or mark them with a `perf` marker excluded from `make test-unit`.
- [ ] If a real test is deadlocking, isolate via binary search (`pytest tests/unit/test_X.py`).
- [ ] Add `pytest-timeout` to dev dependencies; set a sane default per-test timeout.
- [ ] After fix: `make test-unit` should complete in <60 s.

## 4. README honesty pass

Strip claims that point to absent code, with a "coming in Phase 2" note. Phase 3 rewrites the README for real.

- [ ] Comment out the `beaver` CLI section if there's a quickstart that invokes it.
- [ ] Comment out the Docker run instructions (server doesn't exist yet).
- [ ] Soften `pip install "beaver-db[remote]"` to "available in 2.0 final".
- [ ] Soften `BeaverClient` references.
- [ ] `guide-deployment.md`: same treatment.

## 5. CI baseline

- [ ] Add a `make ci` target: `format-check && mypy && pytest tests/unit`. Single command, exit-code clean.
- [ ] Add a minimal GitHub Actions workflow at `.github/workflows/ci.yml` that runs `make ci` on push + PR. Matrix: Python 3.12 only for now.
- [ ] Confirm green on a fresh push.

## Exit checklist

Phase 0 is done when:

- [ ] Inventory captured.
- [ ] LSH / batched / sketches each have a passing smoke test.
- [ ] `make test-unit` runs to green in <60 s.
- [ ] README + `guide-deployment.md` no longer reference absent code.
- [ ] `make ci` target lands; GitHub Actions CI is green on `main`.

Once these tick, we open the Phase 1 tracker (issue 38) and move on.

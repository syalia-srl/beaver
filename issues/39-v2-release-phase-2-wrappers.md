---
number: 39
title: "v2.0 release: Phase 2 — wrappers (CLI / server / client)"
state: open
labels:
- release
- 2.0
---

Phase 2 of the v2.0 release plan. Wrappers layer: make every README promise
true. Tag-able as `2.0rc5` on exit.

Full plan: `vault/Atlas/Architecture/2026-05-15-beaver-v2-release-plan.md`.

Time-box: ~10 days. Exit condition: every README claim is real;
`pip install beaver-db[full]`, `beaver serve`, `BeaverClient("http://...")`,
and `beaver dict mydict get foo --raw | jq` all work; `2.0rc5` tag-able.

Phase 1 (issue #38) closed on 2026-05-15 with `2.0rc4`. Storage engine is
feature-complete: ETL `.dump()` / `.load()` (JSON + JSONL), `.batched()` API
on 6/7 managers, concurrency tests in `tests/concurrency/`. HNSW (#28) was
dropped from scope — beaver vector indexing is numpy-only.

## 1. SID consumers (issue #36) — recommended path

The architectural keystone. One `@expose` decorator on `AsyncBeaver*`
methods; CLI, REST server, and `BeaverClient` all auto-generate from
introspection. New modules:

- [ ] `beaver/api.py` — `@expose` decorator + endpoint metadata.
- [ ] `beaver/cli/discovery.py` — typer generator from introspected managers.
- [ ] `beaver/server.py` — FastAPI route generator (uses the existing
  `[remote]` extra — `fastapi[standard]` is already declared).
- [ ] `beaver/client.py` — httpx proxy implementing the same `IBeaver*`
  protocols as the local managers, so it's a drop-in.
- [ ] `beaver/__init__.py` — universal `beaver.connect("./db.sqlite" |
  "http://host:port")` factory that returns `BeaverDB` or `BeaverClient`
  based on the URI scheme.

Acceptance: a single `@expose` annotation on a manager method makes that
method callable via CLI subcommand, REST endpoint, and `BeaverClient`
proxy with no further wiring.

**Fallback if SID proves nasty:** hand-write CLI + server + client
(~1 week instead of ~10 days). Throwaway when SID lands later, but
unblocks the release if SID stalls.

## 2. Admin commands (issue #15)

Layered on top of the auto-generated CLI from §1. The Unix-citizen UX
features that make `beaver` feel native to the shell.

- [ ] `beaver info` — dashboard view of the database (managers, counts,
  size, last-write per manager).
- [ ] `beaver repl` — interactive shell with the connected DB in scope.
- [ ] `--raw` flag — strip the rich rendering for piping
  (`beaver dict cfg get foo --raw | jq`).
- [ ] `-` for stdin input on write commands
  (`echo '{"k": 1}' | beaver dict cfg set foo -`).
- [ ] `beaver clear <manager> <name>` — quick destructive admin op.
- [ ] `beaver compact` — vacuum + LSH/snapshot rebuild trigger.

Acceptance: each command works, `--help` is useful, stdin/stdout pipe
cleanly through unix tools.

## 3. Docker image rebuilt against the real server

The `dockerfile` already exists from v1; it builds an image meant to
run `beaver serve`. Verify it actually starts a server now that
`beaver/server.py` exists.

- [ ] Confirm `dockerfile` builds clean against current code.
- [ ] Confirm `docker run -p 8000:8000 beaver-db:latest` starts the
  server and serves `GET /health` (or equivalent).
- [ ] Smoke test: `BeaverClient("http://localhost:8000")` round-trips a
  dict set/get against the container.

## 4. API/CLI tests (issue #19 Phase 4)

The impossible-until-now layer. Once §1 is real, these become tractable.

- [ ] `httpx` against a `pytest`-managed `beaver/server.py` instance
  for every exposed endpoint (set, get, push, etc.).
- [ ] `typer.testing.CliRunner` against the auto-generated CLI for
  every subcommand.
- [ ] One round-trip test that proves CLI → server → DB → server → CLI
  symmetry on a bound port.

Acceptance: STATUS.md `SID consumers` and `CLI admin commands` rows
flip to ✅; new `tests/api/` and `tests/cli/` suites green in `make ci`.

## Exit checklist

Phase 2 is done when:

- [ ] STATUS.md wrappers rows all green.
- [ ] `make ci` green; coverage ≥80%.
- [ ] `pip install beaver-db[full]` installs cleanly on a fresh venv.
- [ ] `beaver --help` is useful; `beaver dict X get foo --raw | jq`
  works end-to-end.
- [ ] `BeaverClient("http://...")` is a drop-in for `BeaverDB("./...")`
  in the integration test suite.
- [ ] Docker image starts a server reachable via `BeaverClient`.
- [ ] `2.0rc5` tag-able. (Don't tag without Alex's go-ahead.)
- [ ] Phase 3 tracker (issue #40 — docs rewrite) opened.

Once these tick, Phase 2 closes and we move to Phase 3 (docs).

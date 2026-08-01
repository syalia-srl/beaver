# AGENTS.md — beaver

You're an AI agent picking up **beaver** (`beaver-db` on PyPI). This file is the door.

## What it is

A **local-first, embedded, multi-modal database for Python**, built on a single
SQLite file. One file, many modalities: dicts, lists, queues, logs, documents
(FTS + fuzzy), vectors (LSH), graphs, blobs, locks, channels and sketches — all
in the same `.db`, all through one facade.

It is a **public library** (`syalia-srl/beaver`, MIT) with real downstream users,
not an internal utility. Its biggest consumer is AInBox (`repos/ainbox`), where
warden, magpie, superbot, peacock, help and pipelines all persist through it.

Read [`design.md`](design.md) first — the living design document, with the vision
and the guiding principles. [`STATUS.md`](STATUS.md) is the running inventory of
what is real versus missing in the v2 cycle.

## The shape of the codebase

    beaver/core.py          the engine: AsyncBeaverDB + the BeaverDB sync facade,
                            _create_all_tables, _check_version, every factory method
    beaver/interfaces.py    IBeaver* protocols — the surface the SID consumers target
    beaver/api.py           @expose / @local_only — how a method reaches CLI + server + client
    beaver/queries.py       the q() filter DSL: Query.__getattr__ builds dotted paths → Filter
    beaver/<modality>.py    dicts, lists, queues, logs, docs, vectors, graphs, blobs,
                            locks, channels, sketches — one module each
    beaver/migrate.py       1.x → 2.x migration
    beaver/cli/             the typer CLI (entry point `beaver`)
    docs/                   Quarto site: guide-*.md (users), dev-*.md (contributors)
    issues/                 numbered issue/spec files, synced with GitHub
    tests/{unit,integration,concurrency}

**Architecture in one paragraph.** `AsyncBeaverDB` is the async core (aiosqlite,
one connection, WAL). `BeaverDB` is the *synchronous facade*: it spins a reactor
thread running the async loop and bridges every call to it through
`BeaverBridge` (the Portal pattern). "Synchronous facade, asynchronous engine" —
so write the real logic in the async class, and the sync surface follows. See
`docs/dev-architecture.md` and `docs/dev-concurrency.md`.

## Conventions

- **Every table is dunder-named** — `__beaver_logs__`, `__beaver_documents__`,
  … (`core.py:63`). The single-prefix form (`beaver_logs`) is *1.x* and its
  presence means a legacy file; see issue #41.
- **The `.db` stays a valid, standard SQLite file.** Anyone must be able to open
  it with `sqlite3`. That is a promise from `design.md`, not a preference.
- **Schema changes are additive.** `_create_all_tables()` runs on *every*
  `connect()` with `CREATE TABLE IF NOT EXISTS`, so a new table simply appears on
  an existing database — no migration. Adding a side table is the house pattern
  (see `__beaver_fts_index__`, `__beaver_trigrams__`, `__beaver_lsh_index__`).
- **`BEAVER_DB_VERSION` (`core.py:42`) is at 1 and moving it is a breaking
  change.** `_check_version` raises `BeaverIncompatibleSchemaError` when a file's
  `user_version` exceeds what the running beaver understands (`core.py:372`), so
  a bump means databases written by the new release **fail to open on the old
  one**. Prefer a design that fits additively; bump only when you have decided to
  break file compatibility on purpose.
- **New capability on a manager? Decorate it.** `@expose(path=…, method=…,
  cli_name=…, cli_help=…)` makes it reachable from the CLI, the REST server and
  the remote client at once; `@local_only("reason")` marks what cannot cross the
  wire (infinite streams, file-level operations). A method with neither is
  local-only *by accident* rather than by decision.
- **Minimal dependencies is a product constraint.** Core is `aiosqlite`, `numpy`,
  `pydantic`, `rich`, `typer`. Heavy things go behind extras (`remote`,
  `security`). In particular, **vector indexing stays pure-numpy** — no
  `hnswlib`, no `faiss`, no compiled deps. The LSH strategy exists precisely so
  scaling did not require one (issue #24); HNSW (#28) stays deferred until a
  pure-numpy ANN beats LSH at >100k vectors.
- **Silence is the bug.** The lesson of issue #41 — beaver opened a 1.x file,
  reported everything empty, and wrote a parallel schema beside the untouched
  data. Nothing errored; that was the problem. When state is partial, stale or
  unmigrated, **say so loudly or degrade to the correct-but-slower path** — never
  return a plausible subset.
- Ships to `main`. English for code, docs, comments and commit messages.

## Working here

    make sync           uv sync --extra security --extra remote
    uv run black .      format (see the warning below)
    make format-check   black --check — test-unit depends on this
    make type-check     mypy
    make test-unit      pytest tests/unit --cov=beaver     ← the default target
    make test-all       every suite, including concurrency
    make ci             format-check + test-unit

`pytest.ini` sets `asyncio_mode = auto` (no `@pytest.mark.asyncio` needed) and a
**30 s timeout** — a test that hangs on a lock fails rather than wedging the run.
Markers: `unit`, `integration`, `concurrency`.

> ⚠️ **`make format` and `make bugfix` commit for you**, and they do it with
> `git commit -am` / `git commit -a`, which sweeps up **every dirty file in the
> tree** — including work from a concurrent session that has nothing to do with
> yours. Use **`uv run black .`** and commit the paths you touched yourself.
> `make format-check` is safe and is what `test-unit` actually gates on.

**Releases:** `NEW_VERSION=x.y.z make release` — runs `test-all`, bumps the
version in `pyproject.toml` *and* `beaver/__init__.py`, commits, tags, pushes and
opens the GitHub release. Don't hand-edit those two version strings.

The GitHub release is what actually ships it: `.github/workflows/release.yaml`
fires on `release: created`, re-runs the suite, publishes to PyPI with
`secrets.PYPI_TOKEN`, then pushes the image to GHCR. A tag alone publishes
nothing.

**Verify against an install, not against the tag — and not against the JSON API
either.** Two things bite here, both observed releasing 2.3.0 on 2026-08-01:

- `https://pypi.org/pypi/<pkg>/<ver>/json` returned **200** while `uv pip install`
  still could not resolve the version. The JSON API and the simple index that
  installers actually read propagate separately, so a 200 there is a proxy
  signal, not proof the package is installable.
- `uv` caches the index, and **`--refresh` does not clear it** — the install kept
  failing with *"there is no version of beaver-db==2.3.0"* long after the simple
  index listed both artifacts. `--no-cache` is what works.

So the real check is a scratch venv that exercises the feature:

```bash
uv venv /tmp/verify && VIRTUAL_ENV=/tmp/verify uv pip install --no-cache "beaver-db==X.Y.Z"
VIRTUAL_ENV=/tmp/verify uv run --no-project python -c "…exercise the new API…"
```

**Issues are files.** `issues/NN-slug.md` with `number / title / state / labels`
frontmatter, round-tripped to GitHub by `make issues` (needs the `gh md-issues`
extension). A substantial feature gets an issue file written *first* — see
[`issues/24-…`](issues/) (LSH strategy) and
[`issues/42-uniform-field-indexing-across-collections.md`](issues/42-uniform-field-indexing-across-collections.md)
(field indexing) for the shape: Summary → the problem with real line references →
Design → costs → delivery order → testing.

## Gotchas paid for in advance

- **FTS5 rejects punctuation in the query string** — tokenize before you hand a
  user's words to `.search()` / `.fts()`. Measured on 2.2.0 against an indexed
  document, three different `OperationalError`s:

  | query | error |
  |---|---|
  | `thing` | — (1 hit) |
  | `what's this?` | `fts5: syntax error near "'"` |
  | `this?` | `fts5: syntax error near "?"` |
  | `a-b` | `no such column: b` |

  The hyphen case is the trap: FTS5 reads `a-b` as a **column filter**, so you
  get a "no such column" error that says nothing about punctuation and sends you
  hunting for a schema bug that isn't there.
- **There is no reranking.** `docs` gives you FTS rank and trigram counts;
  combining lexical and vector results is the caller's job (roll your own RRF).
- **Embeddings are not part of `docs`.** A `docs()` collection and a `vectors()`
  collection are separate things you keep in sync yourself; `docs` never embeds.
- **`docs().where()` is a full scan today** — it compiles to `json_extract` per
  row (`docs.py:472`), which is fast but not an index. Issue #42 is the fix.
- **`__beaver_priority_queues__` has no declared PRIMARY KEY.** Its implicit
  `rowid` is the only stable per-item identity. Any code assuming every table
  declares a PK is wrong.
- **`log()` resolves timestamp collisions by micro-incrementing and retrying**
  (`logs.py:96`). Under many concurrent writers that loop can spin — use
  `batched()`, which enforces monotonicity up front.

## Where the planning lives

Design docs and the v2 release plan live in Alex's workspace vault
(`vault/Atlas/Architecture/2026-05-15-beaver-v2-release-plan.md`), not in this
repo — this repo carries `design.md`, `STATUS.md` and `issues/`. If you need the
wider roadmap and cannot see the vault, ask rather than guess.

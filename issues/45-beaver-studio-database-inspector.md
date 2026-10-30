---
number: 45
title: "Beaver Studio: a safe, semantic database inspector"
state: open
labels:
- enhancement
- documentation
---

# Summary

Beaver needs an administrative interface that explains a database in Beaver
terms. A generic SQLite browser can show the underlying tables, but it does not
understand namespaces, modalities, TTLs, side indexes, queue semantics, vector
metadata, graph edges, locks, or sketches. It can also make writes that bypass
the invariants maintained by Beaver's managers.

Build **Beaver Studio** as a local web application, opened with:

```bash
beaver studio --db app.db
```

Studio should open on `127.0.0.1`, inspect the database without modifying it,
and present modality-specific views for dictionaries, lists, queues, logs,
documents, vectors, graphs, blobs, channels, sketches, and locks. Read-only is
the product's default and the MVP's entire permission model. Editing, free-form
SQL, and persistent audit logging are explicitly later decisions.

The frontend must consume a stable, typed inspection API rather than querying
dunder tables directly. The same inspection layer should first power
`beaver info`; this gives the repository a useful administrative command and
validates the contract before a browser UI depends on it.

# Why this is the right UI

The core product promise is one standard SQLite file containing many data
modalities. The most useful interface therefore answers four questions:

1. What is in this file?
2. How can I inspect each structure without changing it?
3. Is the database healthy, compatible, and correctly indexed?
4. What is changing now?

A log viewer answers only part of the fourth question. A raw SQLite browser
answers the first question at the storage level while discarding the semantic
layer that makes Beaver useful. Studio should combine inventory, exploration,
and diagnostics without pretending that all modalities behave like tables.

## Alternatives considered

| Alternative | Strength | Limitation |
|---|---|---|
| Generic SQLite browser | Available today; exposes the standard file format | Does not understand Beaver semantics and can bypass manager invariants |
| Textual TUI | Lightweight and particularly good for terminal log streams | Awkward for graphs, blob previews, rich JSON, and remote use |
| Local web application | Supports tables, search, previews, charts, graphs, accessibility, and remote evolution | Requires a small administrative API and packaged static assets |

`examples/textual_chat.py` proves that Textual can consume Beaver and remains a
good basis for a future TUI. It should not become a core dependency, and it is
not the preferred primary interface.

# Current repository state

Beaver already has useful building blocks:

- `beaver/core.py` owns `AsyncBeaverDB`, the synchronous `BeaverDB` portal,
  schema creation, version checks, transactions, and all manager factories.
- `beaver/interfaces.py` describes the shared interface definitions.
- `beaver/api.py` defines `@expose` and `@local_only`.
- `beaver/server.py` generates FastAPI routes from exposed methods.
- `beaver/client.py` mirrors exposed methods over HTTP.
- `beaver/cli/discovery.py` generates Typer commands from the same metadata.
- `beaver/indexing.py` can report declared field indexes and whether they are
  complete.
- issue #15 already proposes `beaver info` and broader administrative commands.

Those pieces do not yet form an inspector:

- The CLI, server, and remote client expose only dictionaries, lists, queues,
  and logs.
- No public API enumerates every modality and namespace in a database.
- Manager read APIs are not uniformly pageable or non-destructive.
- `where=` filters and `explain()` do not yet have a CLI/wire encoding; issue
  #44 tracks that gap.
- `AsyncBeaverLog.live()` is local-only and uses polling; there is no remote
  SSE or WebSocket stream.
- The priority queue has no declared primary key. Its `rowid` is the only
  stable per-item identity, so a generic primary-key assumption is incorrect.

The existing SID remains the right contract for application operations. Studio
needs a separate administrative contract because inventory, health, redaction,
pagination, and non-destructive browsing are not ordinary manager mutations.

# Read-only must mean no writes

This is a prerequisite, not a polish item.

`AsyncBeaverDB.connect()` currently applies pragmas, calls
`_create_all_tables()`, and stamps `PRAGMA user_version`. Opening a file merely
to inspect it can therefore modify the file. Studio needs a genuine read-only
connection path with these properties:

- open SQLite through a URI using `mode=ro`;
- do not change journal mode or other persistent pragmas;
- do not create missing tables;
- do not stamp `user_version`;
- retain legacy, split-brain, and incompatible-schema detection;
- fail loudly when the file is absent, partial, stale, or unsupported;
- never silently present a plausible subset of an incompatible database.

Opening read-only must not create a database when the path is misspelled. Tests
must compare file metadata and schema before and after a Studio session to prove
that inspection did not write.

# Proposed architecture

```text
Browser
  └── packaged Beaver Studio assets
        └── versioned /admin API
              └── AsyncBeaverInspector
                    └── read-only SQLite connection
                          └── one standard .db file
```

The frontend must not know physical table names. A Python inspection layer maps
the internal schema to stable models and modality-specific pages. That keeps
storage changes, redaction rules, and compatibility checks on the server side.

## Inspection models

The initial contract should include typed, JSON-serializable models similar to:

```python
class DatabaseInfo(BaseModel):
    path: str
    size_bytes: int
    beaver_version: str
    schema_version: int
    journal_mode: str
    read_only: bool
    warnings: list[str]


class CatalogEntry(BaseModel):
    kind: str
    name: str
    count: int | None
    count_is_exact: bool
    capabilities: list[str]
    status: str
    warnings: list[str]


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None
    total: int | None
    total_is_exact: bool
```

The exact types should follow repository conventions, but the contract needs to
distinguish unknown from zero, estimated from exact, unsupported from empty,
and incomplete from healthy. Silence or a plausible subset is not acceptable.

## Inspector responsibilities

`AsyncBeaverInspector` should provide:

- database identity, version, journal mode, size, and compatibility status;
- a catalog of all known modality/name pairs;
- progressive or deferred counts for expensive collections;
- field-index manifests, completeness, and row counts;
- non-destructive, bounded, pageable readers per modality;
- summaries that avoid loading blob payloads or full vectors by default;
- explicit warnings for encrypted, malformed, or partially indexed data;
- optional discovery of unrelated SQLite tables in a separate raw-schema view.

A synchronous `BeaverInspector` bridge is useful only if it provides value
outside Studio. It should not be added merely for symmetry.

## Administrative HTTP surface

Keep administrative routes separate from application CRUD routes. A possible
first version is:

```text
GET /admin/v1/info
GET /admin/v1/catalog
GET /admin/v1/stores/{kind}/{name}/items
GET /admin/v1/stores/{kind}/{name}/indexes
GET /admin/v1/logs/{name}/entries
GET /admin/v1/schema
```

Every endpoint must impose maximum page sizes, validate `kind` against an
allowlist, return the standard Beaver error envelope, and expose whether a
result is complete. Advanced filtering should wait for issue #44 or use a small
typed filter model rather than accepting arbitrary SQL fragments.

The administrative API is a new public compatibility surface. Version it from
the beginning and keep it narrower than the internal inspector.

## Packaging

Ship static assets in the Python distribution. Node may be used to build them,
but must not be required at runtime and no asset should depend on a CDN. For the
MVP, well-structured vanilla TypeScript or a small component library is
preferable to a large frontend framework.

Use a `studio` optional extra rather than expanding the core dependency set.
It can reuse FastAPI from the existing remote stack. The precise relationship
between `remote`, `full`, and `studio` must be documented and tested.

# User experience

## Overview

The landing page should show:

- file path and size;
- Beaver package and schema versions;
- WAL/journal status and read-only status;
- modality and namespace counts;
- active locks and expiring waiters;
- incomplete or stale field indexes;
- compatibility, corruption, and migration warnings;
- unrelated SQLite tables, clearly separated from Beaver data.

Counts should load progressively where `COUNT(*)` may be expensive. The UI must
label estimates and delayed values rather than freezing the overview.

## Shared explorer shell

All stores use a common navigation and detail pattern:

- modality and namespace navigation on the left;
- a bounded, pageable result view in the center;
- an expandable JSON/metadata detail panel on the right;
- explicit loading, empty, error, redacted, and incomplete states;
- copy and export actions that preserve JSON types;
- keyboard navigation and accessible labels;
- safe rendering of stored strings, including hostile HTML.

The common shell must not force all modalities into the same behavior.

## Modality-specific views

### Dictionaries

Show key, decoded value, TTL, and expiration. Encrypted dictionaries must appear
locked or redacted unless a user explicitly provides a secret for the current
session. Secrets stay in memory and never enter logs or URLs.

### Lists

Show logical index and value. Internal fractional ordering keys may appear in a
diagnostic detail, not as the primary user-facing identity.

### Priority queues

Show `rowid`, priority, insertion timestamp, and value without consuming or
reordering anything. Browsing must leave both count and dequeue order unchanged.

### Logs

Provide time-range selection, ascending/descending order, bounded pagination,
JSON details, field-index state, and a follow mode. Incremental polling must use
the last confirmed timestamp rather than the viewer's wall clock.

### Documents

Show document ID, body, FTS/fuzzy search, metadata filters, sorting, and query
plan information. Search input must account for FTS5 punctuation rather than
passing untrusted text directly to FTS syntax.

### Vectors

List ID, dimension, norm, and metadata. Do not serialize full vectors in catalog
or list responses. Provide full data and nearest-neighbor experiments only on
demand, with clear labeling of exact versus LSH results.

### Graphs

Offer an edge table first, followed by a bounded node-neighborhood view. Large
graphs must never be loaded wholesale into the browser.

### Blobs

List key, byte size, and metadata without loading payloads. Fetch payload only
for an explicit preview or download, enforce preview-size limits, and render
active content safely.

### Channels

Show bounded message history and timestamps. Listening to new messages is a
later streaming capability; the history view must work without starting an
unbounded subscription.

### Sketches

Show sketch configuration, expected error, capacity, and approximate
cardinality. Membership checks may be added as an explicit tool.

### Locks

Show lock/waiter identity, age, TTL, and expiration status. Releasing or clearing
a lock is a destructive administrative action and is outside the MVP.

# Logs, events, and auditability

Studio must distinguish three different concepts:

1. **Stored logs** are user data written through `db.log(name)`.
2. **Mutation events** are manager callbacks transported through channels.
3. **Operational diagnostics** are records emitted through Python's `beaver`
   logger by the engine, server, or Studio process.

Mutation events are not an audit trail today:

- managers emit them only after an event manager has been initialized;
- event emission failures are currently swallowed;
- not every modality exposes identical event detail;
- payloads may include sensitive application values;
- changes made outside Beaver cannot be reconstructed from those events.

The MVP should therefore:

- browse and follow intentional `db.log()` streams;
- capture operational logs from the Studio process into a bounded in-memory
  buffer;
- use `PRAGMA data_version` or an equivalent correct mechanism to notice writes
  made by other connections and refresh affected views;
- avoid claiming that it records every database operation.

Do not write an automatic activity log into the inspected database. A later,
opt-in audit facility may use an additive `__beaver_audit__` table, but only
after defining redaction, retention, recursion prevention, overhead, raw-SQL
limitations, and transactional guarantees. Adding such a table would not by
itself require a `BEAVER_DB_VERSION` bump under the repository's additive schema
policy.

# Security and safety

The MVP is read-only. That removes many risks but does not remove data exposure
or browser security concerns.

- Bind to `127.0.0.1` by default.
- Refuse a non-loopback bind without authentication.
- Use a separate admin credential when Studio inspects a remote server.
- Never place API keys or dictionary secrets in query strings.
- Escape all stored content and test against stored XSS payloads.
- Limit JSON depth, row size, page size, blob preview size, and response time.
- Redact encrypted values, binary payloads, and full vectors by default.
- Do not emit stored values in access or diagnostic logs by default.
- Keep raw SQL outside the MVP.
- Show an unmistakable persistent badge for read-only versus future write mode.

If write mode is added later, it must be enabled explicitly with `--write`, use
manager APIs rather than direct SQL, protect browser mutations against CSRF,
distinguish permissions by operation, and require confirmation for destructive
actions such as `clear`, dequeue, lock release, or reindexing.

# Delivery plan

## Phase 0: specification and truthfulness

1. Agree on the MVP, security contract, and supported modalities in this issue.
2. Decide whether the first release is local-only; local-only is recommended.
3. Correct high-risk documentation claims that currently describe removed or
   unreleased APIs.

## Phase 1: inspection foundation

1. Add a genuine read-only connection path.
2. Define `DatabaseInfo`, `CatalogEntry`, pageable results, and warnings.
3. Implement the catalog across every official Beaver table.
4. Implement safe summaries and readers for dict, list, queue, and log.
5. Expose the catalog through `beaver info` before building the browser UI.

This phase proves the hard part: a correct semantic inventory that never alters
the file.

## Phase 2: administrative API

1. Add versioned, authenticated `/admin` routes.
2. Add bounds, validation, error envelopes, and response completeness metadata.
3. Cover local and remote behavior without conflating admin routes with SID
   application routes.

## Phase 3: Studio MVP

1. Add `beaver studio --db FILE` with loopback-only defaults.
2. Package an offline static frontend.
3. Implement overview, navigation, pagination, JSON details, and error states.
4. Support dictionaries, lists, queues, and logs.
5. Add log follow by bounded incremental polling; streaming can wait.

## Phase 4: complete modality coverage

Add documents, vectors, graphs, blobs, channels, sketches, locks, raw schema,
index diagnostics, and in-memory operational logs. Each modality ships only when
its list operation is bounded and non-destructive.

**Branch status:** phases 1–4 are implemented on
`docs/beaver-studio-proposal`. All modality lists are bounded and read-only;
vectors and blobs require explicit bounded detail requests; external schema,
index health, and in-memory Studio operations are exposed without free-form SQL.
Phase 5 remains intentionally separate.

## Phase 5: optional administration

Evaluate write mode, reindex controls, backup/export workflows, remote Studio,
SSE/WebSockets, a TUI, free-form read-only SQL, and persistent auditing as
separate capabilities. None should delay a useful read-only inspector.

# Testing strategy

## Inspector and read-only behavior

- Empty and populated databases.
- Every modality and multiple namespaces per modality.
- Namespace names containing spaces, Unicode, quotes, and punctuation.
- Existing database gains no tables and no `user_version` change.
- Missing path does not create a file.
- Legacy, split-brain, incompatible, and partial schemas fail loudly.
- Unrelated SQLite tables are not misclassified as Beaver stores.
- Counts distinguish exact, estimated, deferred, and unavailable.
- Encrypted dictionaries, malformed JSON, and unknown rows degrade explicitly.

## Modality invariants

- Queue browsing changes neither count nor dequeue order.
- Blob listings do not read payloads.
- Vector listings do not return full vectors.
- Graph browsing stays bounded.
- Log cursors neither duplicate nor omit entries at page boundaries.
- Field-index views report incomplete manifests accurately.
- Expired dictionary values are represented consistently without requiring a
  cleanup write from the read-only inspector.

## HTTP and browser

- Authentication and rejection of unsafe external binds.
- Maximum page and response sizes.
- Invalid modality/name/filter handling.
- Standard error envelopes and appropriate HTTP status codes.
- No mutation routes in read-only mode.
- Stored XSS payloads, deep JSON, large values, and malformed UTF-8/binary data.
- Loading, empty, partial, redacted, timeout, and error states.
- Keyboard navigation and basic accessibility.

## Integration and concurrency

- Run Studio in a real subprocess.
- Inspect while another process writes under WAL.
- Confirm refresh behavior through `data_version` or its chosen replacement.
- Exercise large logs, blobs, vectors, and graphs without loading them entirely.
- Test transaction timeouts and Studio shutdown without leaked threads/tasks.

## Documentation

- Execute the quickstart and critical snippets.
- Test documented CLI commands with `CliRunner`.
- Build the Quarto site in CI.
- Check documented factories and commands against current interfaces and
  `@expose` metadata.

# User manual plan

The final manual should follow stable, tested workflows rather than mirror the
module tree. Studio screenshots and instructions should be added after its
interactions settle. Before then, apply a small honesty pass because the current
documentation contains materially obsolete claims:

- `README.md` still says the CLI and server will arrive in 2.0, although the
  package is already 2.4.1.
- `docs/intro.md` describes zero dependencies, FAISS, and obsolete extras.
- `docs/quickstart.md`, `docs/guide.md`, and
  `docs/guide-collections.md` use the removed monolithic `db.collection()` API
  instead of separate `docs()`, `vectors()`, and `graph()` managers.
- `docs/dev-architecture.md` documents 1.x single-prefix table names.
- several guides use obsolete `.as_async()`, `.match()`, `--database`, blob,
  log, and deployment APIs.
- `STATUS.md` still describes the pre-2.0 delivery cycle.

The rewritten manual should contain:

1. When to use Beaver and where its boundaries are.
2. Installation and the first database.
3. Synchronous and asynchronous usage.
4. One task-oriented guide per modality.
5. Separate document, vector, graph, FTS, fuzzy, and field-filter workflows.
6. Transactions, concurrency, WAL, queues, channels, and locks.
7. Beaver Studio and safe inspection.
8. CLI, server, authentication, and remote client.
9. Export, restore, backup, and migrations.
10. Security, encrypted dictionaries, and secret handling.
11. Indexing, performance, limits, and query diagnostics.
12. Troubleshooting and compatibility failures.

The repository convention requires English code and documentation. A Spanish
manual can be published later, but it needs an explicit maintenance policy so
that it does not become a second source of stale API claims.

# Documentation file plan

After Studio is approved and implemented:

## Create

- `docs/guide-studio.md`
- `docs/guide-documents.md`
- `docs/guide-vectors.md`
- `docs/guide-graphs.md`

## Rewrite or update

- `README.md`
- `STATUS.md`
- `docs/intro.md`
- `docs/quickstart.md`
- `docs/guide.md`
- `docs/guide-collections.md`
- `docs/guide-blobs.md`
- `docs/guide-logs.md`
- `docs/guide-channels.md`
- `docs/guide-deployment.md`
- `docs/dev-architecture.md`
- `docs/_quarto.yml`

`guide-collections.md` should either become an overview linking documents,
vectors, and graphs or be removed after redirects are considered. Do not retain
the old monolithic collection model as if it were current.

# Likely implementation footprint

The eventual implementation is expected to touch or create the following areas;
this list is directional rather than approval to implement them now.

## Likely new files

- `beaver/admin.py` for inspector models and behavior.
- `beaver/studio/` for the FastAPI integration and packaged assets.
- `tests/unit/test_admin.py`.
- `tests/unit/test_studio.py`.
- `tests/integration/test_studio_subprocess.py`.

## Likely modified files

- `beaver/core.py` for read-only connection semantics.
- `beaver/interfaces.py` if inspector types become public.
- `beaver/server.py` for optional administrative mounting.
- `beaver/cli/main.py` for `info` and `studio`.
- `beaver/__init__.py` if public connection options change.
- `pyproject.toml` for the `studio` extra and packaged assets.
- the documentation listed above.

No schema version bump is expected for the inspector or UI. A future additive
audit table should also fit the existing additive schema policy unless its
semantics deliberately break backward file compatibility.

# Risks

- The administrative API may accidentally become broad and hard to evolve.
- A supposed read-only path may still write through pragmas, expiration cleanup,
  or manager side effects.
- Exact counts may make the overview slow on large databases.
- A universal tabular abstraction may hide destructive or modality-specific
  semantics.
- Filter encoding may introduce unsafe SQL or disagree with Python filters.
- Polling logs by wall-clock time may omit or duplicate entries.
- Stored content may attack the browser through XSS or oversized payloads.
- Exposing Studio outside loopback may leak the entire database.
- Event streams may be mistaken for a complete audit trail.
- Documentation drift may persist if examples are not executed in CI.
- Manager singleton caching currently ignores changed constructor kwargs on a
  cache hit; issue #43 may affect administrative/indexed manager creation.

# Decisions to make before implementation

1. Is the first Studio release exclusively local? Recommended: yes.
2. Does Studio use a new optional extra? Recommended: `studio`.
3. Which frontend toolchain is acceptable? Recommended: packaged vanilla or a
   very small TypeScript application for the MVP.
4. Are unrelated SQLite tables visible? Recommended: yes, in a separate
   read-only raw-schema panel.
5. Does the MVP include writes? Recommended: no.
6. Does it persist operational logs? Recommended: no; use a bounded in-memory
   buffer first.
7. Are catalog counts always exact? Recommended: allow progressive/deferred
   exact counts and label them.
8. Does the MVP include arbitrary SQL? Recommended: no.
9. Must issue #44 land before Studio? Recommended: only before advanced shared
   filters; typed modality-specific filters can support the early MVP.
10. Will translated manuals be maintained? Recommended: choose one canonical
    English source before adding translations.

# Definition of done for the MVP

- `beaver studio --db FILE` opens an offline-capable local browser UI.
- The command binds to loopback and opens the database in proven read-only mode.
- The overview identifies every Beaver modality and namespace without silently
  omitting incompatible or malformed state.
- Dict, list, queue, and log data can be browsed with bounded pagination.
- Queue browsing and every other Studio operation leave the database unchanged.
- Logs support historical ranges and safe incremental follow.
- Sensitive and oversized values are redacted or fetched explicitly.
- The administrative API is versioned, bounded, authenticated where required,
  and tested.
- Large databases remain responsive because no view loads a complete store.
- The CLI exposes the same inventory through `beaver info`.
- The user manual reflects the real 2.x API, and its critical examples execute
  in CI.

Studio succeeds when a developer can open an unfamiliar Beaver file, understand
what it contains, identify warnings, and inspect representative data without
learning the dunder schema or risking a mutation.

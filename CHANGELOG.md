# Changelog

All notable changes to beaver-db will be recorded here.

## 2.2.0 — 2026-07-29

### Fixed — data-loss class (#41)

- **beaver 2.x no longer opens a beaver 1.x database silently.** 1.x named its
  tables `beaver_dicts` / `beaver_lists` / …; 2.x uses the dunder form
  (`__beaver_dicts__`, …), and the version check only inspected the dunder
  names. So a genuine 1.x file **opened without error and reported every dict,
  list and collection as empty**, then wrote a second, parallel dataset beside
  the untouched originals — leaving the database split-brain, where rolling back
  to 1.x loses the new writes and staying on 2.x leaves the original data
  unreachable. Nothing signalled that a migration was due.

  Opening a 1.x database now raises **`BeaverLegacySchemaError`** (a subclass of
  `BeaverIncompatibleSchemaError`, so existing handlers keep working). A
  split-brain file gets a distinct, louder error. Both name the detected 1.x
  version and point at `docs/migration-1x-to-2x.md`. Detection keys on the
  presence of an explicit set of 1.x table names — not a `beaver_%` prefix — so
  an unrelated user table cannot trigger a false refusal, and it runs *before*
  the `user_version` fast path, which a split-brain file would otherwise skip.

  **Upgrading with existing data:** this is deliberately a hard failure. Run
  `beaver migrate` (below) before pointing 2.2 at a 1.x database.

### Added

- **`beaver migrate <path>`** — one-way 1.x → 2.x database migration.
  `--dry-run` reports rows per store, list orderings to regenerate, indices to
  rebuild and tables to drop *with a reason each*, and predicts the real run
  exactly. `--output` chooses the destination.

  The source is opened **read-only** and is never a participant in the write
  path — it cannot be mutated, even by a WAL checkpoint. The destination is
  always a new file; the command prints the `mv` commands to adopt it, so there
  is no window in which a half-migrated database is the only copy.

  Mapping: dicts, blobs, logs, priority queues, sketches and edges copy straight
  across; list ordering is regenerated (1.x `item_order` was a `REAL` midpoint
  scheme, 2.x is a fractional index); `beaver_collections` **fans out into two
  tables** (`__beaver_documents__` + `__beaver_vectors__`), with document bodies
  stored verbatim and vectors copied byte-for-byte; FTS and trigram indices are
  rebuilt; ephemeral and cache-bookkeeping tables are dropped. Dict values move
  as opaque text, so encrypted values round-trip without the tool holding key
  material. Split-brain databases are refused rather than merged — deciding
  which writes win is an application-level judgement.

- `BeaverLegacySchemaError` exported from `beaver` and registered in the error
  registry.
- `docs/migration-1x-to-2x.md` — the schema diff and the migration procedure.

### Fixed

- `BeaverDB.__init__` now tears down its reactor thread when `connect()` fails,
  instead of leaking a thread and event loop. Previously `connect()` almost
  never raised; with the check above it legitimately can.

## 2.1.0 — 2026-07-18

### Added

- **`docs.search()` filtered/range search.** `search(query=None, *, on=None,
  where=None, sort=None, limit=None, offset=None, fuzzy=False)` — the
  `where`/`sort`/`limit`/`offset` keywords make metadata-filtered and numeric-range
  document queries usable through the **sync** portal (previously only the async
  fluent `query()...where()...execute()` builder could express them). Backward
  compatible with the positional `search(query, on, fuzzy)` form.

### Known issues

- **`col.batched()` re-entry deadlock (#40).** A second *large* batched write on a
  collection under the sync portal can deadlock (the `executemany` self-locks with
  `BEGIN IMMEDIATE` held). Workaround: use one `batched()` context per collection.

## 2.0.0 — 2026-06-27

Final 2.0 release (concludes the `2.0rc*` series above).

## 2.0rc5 — 2026-05-25

### Fixed

- **`AsyncListBatch.flush()` still used float arithmetic on `item_order`.**
  After `2.0rc4` migrated the column to TEXT fracdex strings, the batched
  push/prepend path was missed: it did `next_order = max_order; next_order
  += 1.0`, which both raises `TypeError` against a string `max_order`
  (any list seeded by non-batched ops) and silently breaks order when
  starting empty (stores `"1.0"..."500.0"` whose lex sort puts `"98.0"`
  past `"500.0"`). Now mints fracdex keys via
  `key_between(prev, None)` / `key_between(None, prev)`. The pre-existing
  `tests/unit/test_batched.py::test_list_batched_bulk_push` was already a
  regression test for this — it had been failing on `main` since rc4.

## 2.0rc4 — 2026-05-24

### Breaking

- **Persistent-list storage format changed.** `__beaver_lists__.item_order`
  is now `TEXT` (fractional index) instead of `REAL`. Fixes a hard crash in
  `AsyncBeaverList.insert()` after ~52 inserts at the same contended index
  (bug-hunt 2026-05-24, float-midpoint collapse against the `UNIQUE`
  constraint on `(list_name, item_order)`).
- Databases created by `2.0rc3` or earlier are rejected on open with
  `BeaverIncompatibleSchemaError`. See
  `docs/migration-rc3-to-rc4-lists.md` for the dump-and-reload recipe.

### Added

- `BeaverIncompatibleSchemaError`, exported from `beaver`.
- DB version tracking via SQLite's built-in `PRAGMA user_version`. Current
  version: `1`.

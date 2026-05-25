# Changelog

All notable changes to beaver-db will be recorded here.

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

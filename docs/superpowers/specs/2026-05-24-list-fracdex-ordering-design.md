---
date: 2026-05-24
type: design
scope: beaver-db
target_release: v2.0rc4
status: draft
---

# Persistent List Ordering: Fractional-Index Strings

## Background

`AsyncBeaverList.insert(index, value)` (`beaver/lists.py:236-257`) computes a new order value as the float midpoint between the two neighbors:

```python
new_order = order_before + (order_after - order_before) / 2.0
```

The column `__beaver_lists__.item_order` is `REAL NOT NULL` and participates in the table's `PRIMARY KEY (list_name, item_order)`. Repeated insertion at a contended index halves the available float gap each step; after ~52 inserts the gap shrinks below the float64 ULP at 1.0 and the computed midpoint rounds to one of the neighbors. The next insert raises:

```
sqlite3.IntegrityError: UNIQUE constraint failed:
  __beaver_lists__.list_name, __beaver_lists__.item_order
```

The exception is a raw `sqlite3` error bubbled through the bridge; there is no library-level translation, no documented limit, and no exposed mitigation. Full bug analysis: `vault/+/agent_drafts/bug_hunts/2026-05-24-beaver.md`.

This is a hard crash on a documented happy-path operation of an advertised headline feature. The fix must be permanent (delete the failure mode, not patch a symptom), transparent (no API change for callers), efficient for small lists, and robust under adversarial insertion patterns at arbitrary scale.

## Goals

1. `insert(index, value)` cannot crash from ordering exhaustion regardless of call pattern.
2. No change to the public list API surface.
3. `prepend`, `push`, `insert` collapse into a single ordering primitive — three special cases become one.
4. Old (rc3-era) database files are detected on open and rejected with an actionable, library-specific exception. No silent data corruption, no surprise migration.

## Non-goals

- Migrating other tables that use `REAL` ordering columns. `__beaver_logs__.timestamp` is monotonic-ish under real-clock semantics; `__beaver_priority_queues__` has no `UNIQUE` constraint on `(queue_name, priority)` and duplicate priorities are well-defined. Neither has the collapse pathology.
- Online migration of rc3 → rc4 databases. The way out for users with existing data is documented dump-on-rc3 + load-on-rc4.
- Preserving the float `item_order` values across the upgrade for callers reading the column directly. The column is internal (double underscores); no public contract.

## Design

### Ordering primitive: fractional indexing

Replace the float-midpoint scheme with **fractional indexing** (the Figma / jsonjoy `fracdex` approach). Keys are short lexicographically-ordered strings over a fixed base-62 alphabet (`0-9A-Za-z`). Between any two distinct keys you can always construct a third key that sorts strictly between them — the key just gets one character longer when neighbors are densely packed. Storage cost is `O(log contention)` per key in the worst case; in practice keys stay short.

New module `beaver/_fracdex.py` exposes a single primitive:

```python
def key_between(a: str | None, b: str | None) -> str:
    """Return a key k such that (a or "") < k < (b or "~~~..."), lex-ordered.

    a=None    → key strictly less than b ("prepend" semantic)
    b=None    → key strictly greater than a ("append" semantic)
    a=None, b=None → midpoint of the key space (first key in an empty list)
    """
```

Properties (enforced by tests):
- `a < key_between(a, b) < b` for all valid `(a, b)`.
- `key_between(None, b) < b` and `key_between(a, None) > a`.
- Output uses only characters in the alphabet `0-9A-Za-z`.
- For any sequence of legal calls the output length grows by at most one character per nesting level.

The module is pure: no I/O, no database, no async. Tested independently with deterministic fuzz over random `(a, b)` pairs and via a "1000 inserts at index 1" stress harness.

### Schema

```sql
CREATE TABLE IF NOT EXISTS __beaver_lists__ (
    list_name TEXT NOT NULL,
    item_order TEXT NOT NULL,
    item_value TEXT NOT NULL,
    PRIMARY KEY (list_name, item_order)
)
```

The column type changes `REAL` → `TEXT`. Primary key unchanged. SQLite still uses lexicographic ordering for `TEXT` PKs, which is exactly what fracdex requires.

### Call-site collapse

`prepend`, `push`, and `insert` all reduce to:

```python
new_key = _fracdex.key_between(left_key, right_key)
INSERT INTO __beaver_lists__ (list_name, item_order, item_value) VALUES (?, ?, ?)
```

with the only difference being which of `left_key` / `right_key` are looked up vs passed as `None`:

| operation       | left_key                         | right_key                        |
|-----------------|----------------------------------|----------------------------------|
| `prepend(v)`    | `None`                           | `MIN(item_order) WHERE list=?`   |
| `push(v)`       | `MAX(item_order) WHERE list=?`   | `None`                           |
| `insert(i, v)`  | `key @ i-1` (or `None` if `i<=0`)| `key @ i` (or `None` if `i>=len`)|

The boundary-redirect branches in `insert()` go away; `insert(0, v)` produces the same effect as `prepend(v)` by simply passing `left=None`. The redundant code in `prepend()` and `push()` for "is the list empty" also collapses into the same primitive.

### Version gate

SQLite has a built-in `PRAGMA user_version` (32-bit integer, persisted in the DB header, free for application use). Beaver does not currently set it, so all existing rc3 databases have `user_version = 0`.

Define `BEAVER_DB_VERSION = 1` in `beaver/core.py`. On `BeaverDB.connect()`:

1. After applying pragmas and before `_init_db()` runs `CREATE TABLE IF NOT EXISTS` statements:
   - Read `PRAGMA user_version` → `v`.
   - If `v == BEAVER_DB_VERSION`: nothing to do.
   - If `v == 0`:
     - Check whether `__beaver_lists__` exists with `item_order` of type `REAL`. Query: `SELECT type FROM pragma_table_info('__beaver_lists__') WHERE name = 'item_order'`.
     - If the table exists with `REAL` and is non-empty (`SELECT 1 FROM __beaver_lists__ LIMIT 1`): raise `BeaverIncompatibleSchemaError`, message points to `docs/migration-rc3-to-rc4-lists.md`.
     - If the table exists with `REAL` but is empty: drop and recreate as `TEXT`. Safe — no data to lose.
     - If the table doesn't exist: it will be created as `TEXT` by `_init_db()`.
   - If `v > BEAVER_DB_VERSION`: raise `BeaverIncompatibleSchemaError` ("database was written by a newer beaver").
2. After `_init_db()` completes successfully on a fresh-or-upgraded DB, set `PRAGMA user_version = 1`.

`BeaverIncompatibleSchemaError` is a new exception in `beaver/errors.py` (or wherever the existing exception hierarchy lives — TBD on first read). Subclass of `BeaverError`. Message template:

```
This database was created by beaver < v2.0rc4 and is not compatible with this
version. The persistent-list storage format changed in rc4.

To migrate: open the database with v2.0rc3, dump each list with
`list(db.list(name))`, then re-create the lists in a new rc4 database.

See: https://github.com/<repo>/blob/main/docs/migration-rc3-to-rc4-lists.md
```

### Other tables — explicitly out of scope

`__beaver_logs__.timestamp REAL`: append-only, time-indexed. No insert-in-middle pathology.

`__beaver_priority_queues__.(priority REAL, timestamp REAL)`: no `UNIQUE` constraint on the ordering tuple, no PK conflict possible from priority collisions. Duplicates dequeue in timestamp order, which is correct behavior.

Both remain `REAL`. No change.

## Tests

New file `tests/unit/test_lists_fracdex.py`:

- `test_insert_at_contended_index_does_not_collapse`: 1000 inserts at index 1 on a 2-element seed list; assert all succeed and the final list is correctly ordered. This is the regression test for the original bug.
- `test_fracdex_fuzz`: random sequence of 10_000 operations (`push`, `prepend`, `insert`, `pop`, `deque`, `__getitem__`) against an in-memory Python list as oracle. Assert state matches after every operation.
- `test_fracdex_key_invariants`: pure unit tests on `_fracdex.key_between` — monotonicity, alphabet, boundary cases, deterministic output.
- `test_fracdex_growth`: 100 inserts at index 1 — assert the longest key length is bounded (≈ log_62(100) ≈ 2).

New file `tests/unit/test_db_version.py`:

- `test_fresh_db_sets_user_version`: open a new DB, assert `PRAGMA user_version == 1`.
- `test_rc3_db_with_lists_raises`: hand-craft a DB with the old `REAL` schema and one row, open with rc4, assert `BeaverIncompatibleSchemaError`.
- `test_rc3_db_with_empty_lists_upgrades`: hand-craft a DB with the old schema and no rows, open with rc4, assert success and `user_version == 1` and column type is `TEXT`.
- `test_newer_db_raises`: hand-craft a DB with `user_version = 99`, open with rc4, assert `BeaverIncompatibleSchemaError`.

Existing `tests/unit/test_lists.py` continues to pass unchanged — the public API surface and observable behavior are preserved.

## Documentation

New file `docs/migration-rc3-to-rc4-lists.md`:

```markdown
# Migrating persistent lists from rc3 to rc4

The persistent-list storage format changed in rc4: `__beaver_lists__.item_order`
is now `TEXT` (fractional index) instead of `REAL`. This removes a crash mode
in `insert()` at contended indices.

Databases created by rc3 or earlier are rejected on open by rc4. To migrate:

1. With rc3 installed, dump each list:

       import json
       from beaver import BeaverDB
       db = BeaverDB("old.db")
       await db.connect()
       dump = {}
       for name in await db.list_names():   # or however your code knows the names
           dump[name] = [item async for item in db.list(name)]
       json.dump(dump, open("lists.json", "w"))

2. Upgrade to rc4 and load into a new database:

       db = BeaverDB("new.db")
       await db.connect()
       dump = json.load(open("lists.json"))
       for name, items in dump.items():
           lst = db.list(name)
           for item in items:
               await lst.push(item)
```

`CHANGELOG.md` entry under rc4:

```
### Breaking
- **Persistent-list storage format changed.** `__beaver_lists__.item_order`
  is now `TEXT` (fractional index). Fixes a crash in `insert()` at contended
  indices (#<issue>). Databases created by rc3 or earlier are rejected with
  `BeaverIncompatibleSchemaError`. See `docs/migration-rc3-to-rc4-lists.md`.
```

## Risks and open questions

- **Fracdex algorithm choice.** The jsonjoy / Figma scheme is the most-validated reference. Worth porting a known implementation (e.g. the Python port in `fractional-indexing` on PyPI is MIT-licensed) rather than rolling our own. Decision: vendor a minimal implementation, ~80 lines, with attribution in the docstring.
- **Where does `BeaverIncompatibleSchemaError` live?** Need to read the existing exception hierarchy in beaver to decide. Likely `beaver/errors.py` or co-located with `BeaverDB`. Resolved during plan execution.
- **`list_names()` in the migration doc.** The snippet assumes a way to enumerate list names. If beaver doesn't expose one, the migration story is awkward — caller must know their list names out-of-band. Worth verifying and either documenting the workaround or adding an enumeration helper as part of this work.

## Confidence

The bug is deterministic and the fix is mechanical. Fractional indexing is a well-trodden solution to exactly this problem in production systems (Figma, Linear, jsonjoy). The version-gate via `PRAGMA user_version` is the SQLite-idiomatic approach and costs nothing.

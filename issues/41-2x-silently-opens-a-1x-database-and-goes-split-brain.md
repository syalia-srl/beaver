---
number: 41
title: "2.x silently opens a 1.x database, reports it empty, then goes split-brain"
state: open
labels:
- bug
- data-loss
- schema
---

### 1. Summary

beaver 2.x **opens a beaver 1.x database without any error**, reports every
dict / list / collection as empty, and then starts writing into a *second,
parallel* set of tables beside the untouched legacy ones.

beaver 1.x names its tables with a single prefix — `beaver_dicts`,
`beaver_lists`, `beaver_collections`, … — while 2.x uses dunder names —
`__beaver_dicts__`, `__beaver_lists__`, …. `AsyncBeaverDB._check_version`
only inspects `__beaver_lists__`, so against a genuine 1.x file it finds
nothing, passes, and `_create_all_tables` then creates a fresh empty dunder
set alongside the legacy tables.

For a consumer upgrading 1.x → 2.x this looks like **total data loss**: the
data is still on disk but invisible. Worse, once 2.x has written anything,
the database is split-brain (old data in `beaver_*`, new writes in
`__beaver_*__`) and rolling back to 1.x silently drops everything written
in the meantime. The silence is the dangerous part — nothing signals that a
migration is due.

Found while migrating AInBox's superbot to beaver 2.x. Three live databases
on the `demos` VPS (`superbot.db`, `magpie.db`, `help.db`) are in exactly
this state.

### 2. Reproduction (verified)

```bash
rm -f probe.db
uv run --with "beaver-db==1.3.0" python -c '
from beaver import BeaverDB
db = BeaverDB("probe.db")
db.dict("conv:c1:meta")["title"] = "My important conversation"
db.list("conv:c1:pairs").push({"user": "hello"})
'
uv run --with "beaver-db==2.1.0" python -c '
from beaver import BeaverDB
db = BeaverDB("probe.db")
print("OPENED WITHOUT ERROR")
print("  dict count:", db.dict("conv:c1:meta").count())
print("  list len:", len(list(db.list("conv:c1:pairs"))))
'
```

Observed on 2.1.0:

```
OPENED WITHOUT ERROR
  dict count: 0
  list len: 0
```

Ground truth for the 1.x file: 20 `beaver_*` tables, `PRAGMA user_version` =
`0`, and a version stamp at `beaver_dicts` where
`dict_name='__metadata__' AND key='version'` holding the JSON string
`"1.3.0"`.

### 3. Why the existing gate misses it

`_check_version` handles two cases today:

- `user_version > BEAVER_DB_VERSION` → written by a newer beaver → reject.
- `__beaver_lists__.item_order` is `REAL` **and** the table has rows → an
  rc3-era 2.0 pre-release → reject (`docs/migration-rc3-to-rc4-lists.md`).

A 1.x database matches neither: `user_version` is `0` (same as a fresh
database) and `__beaver_lists__` does not exist at all. Keying detection on
the *absence* of dunder tables is not an option either — a brand-new
database has none, and `_check_version` runs before `_create_all_tables`.

### 4. Fix — slice 1: detect and refuse

Discriminate on the **presence of single-prefix `beaver_*` tables**. Verified
against the 2.x source: every `CREATE TABLE` in the package uses a dunder
name, so 2.x never produces a single-prefix table, making their presence a
clean positive signal.

Two distinct outcomes:

- Legacy tables only → the database was written by 1.x and never touched by
  2.x. Refuse with a message naming the detected 1.x version.
- Legacy **and** dunder tables → split-brain; someone already opened it with
  2.x by accident. Refuse with a louder message warning that a rollback to
  1.x now loses the 2.x-side writes.

The check must run *before* the `user_version == BEAVER_DB_VERSION` early
return, because a split-brain database has already been stamped to the
current version by the accidental 2.x open.

Must not regress: fresh databases, existing 2.x databases, `:memory:`, and
the rc3 lists check.

### 5. Slice 2: in-place migrator (design only)

The legacy tables are ordinary SQLite that 2.x can read directly, so a
single-process, in-place `beaver_*` → `__beaver_*__` migration is feasible
with no 1.x install. Design lives in
`docs/migration-1x-to-2x.md`; not implemented yet — needs sign-off from the
consumer side (AInBox) before it lands.

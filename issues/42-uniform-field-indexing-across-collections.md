---
number: 42
title: "Uniform field indexing and filtering across every collection with per-item JSON"
state: open
labels:
- enhancement
- query
- performance
---

## 1. Summary

beaver stores a JSON document per item in **nine of its ten collection types**,
but only `docs` can filter on a field inside it — and even there the filter is
an **unindexed full scan**. Every other collection can only be sliced by its
primary key.

This issue proposes **one primitive, identical in every collection**: declare
which fields to index when you open the collection, then filter, sort, paginate
and aggregate on them through the existing `q()` query DSL. No collection grows
a bespoke query API, and no consumer ever drops to SQL.

The change is **purely additive to the schema**: one new side table, no
`ALTER TABLE`, and `BEAVER_DB_VERSION` stays at `1`. Existing databases gain the
feature by being opened.

## 2. The problem, concretely

### 2.1 Where per-item JSON already lives

| collection | factory | table | JSON column | item key |
|---|---|---|---|---|
| dicts | `db.dict` | `__beaver_dicts__` | `value` | `key` |
| lists | `db.list` | `__beaver_lists__` | `item_value` | `item_order` |
| logs | `db.log` | `__beaver_logs__` | `data` | `timestamp` |
| documents | `db.docs` | `__beaver_documents__` | `data` | `item_id` |
| queues | `db.queue` | `__beaver_priority_queues__` | `data` | `rowid` ¹ |
| channels | `db.channel` | `__beaver_pubsub_log__` | `message_payload` | `timestamp` |
| blobs | `db.blob` | `__beaver_blobs__` | `metadata` ² | `key` |
| vectors | `db.vectors` | `__beaver_vectors__` | `metadata` ² | `item_id` |
| graphs | `db.graphs` | `__beaver_edges__` | `metadata` ² | `(source, target, label)` |

¹ `__beaver_priority_queues__` declares **no** `PRIMARY KEY`; its implicit
`rowid` is the only stable per-item identity. Any design that assumes a declared
PK on every table is wrong.

² Three collections store the item's payload as a `BLOB` and its metadata in a
separate `metadata TEXT` column. So the primitive must address "the item's JSON",
which is the payload column in six collections and the metadata column in three.

`__beaver_sketches__` has no per-item JSON and is out of scope.

### 2.2 What you can do today

Only `docs` filters by field, via `DocumentQuery.where()`. It compiles to

```python
# beaver/docs.py:472-476
where.append(f"json_extract(d.data, '$.{filter.path}') {filter.operator} ?")
```

which is a **full scan of the collection** — SQLite evaluates `json_extract` for
every row. It is much faster than filtering in Python (no deserialization, no
row transfer), but it is not an index, and it degrades linearly.

Everything else has no field filtering at all. `AsyncBeaverLog.range()`
(`beaver/logs.py:106`) accepts `start`, `end`, `limit` — nothing more — with
`ORDER BY timestamp ASC` hardcoded at line 120 and no `offset`. A consumer that
wants "the 50 most recent entries by user X" must load the entire log into
memory and filter in Python. That is the motivating case (see §7).

### 2.3 What beaver already does right, and should be copied

`docs` maintains **side index tables** populated at write time and JOINed at
query time: `__beaver_fts_index__` (FTS5) and `__beaver_trigrams__`, the latter
written by `_index_trigrams` (`beaver/docs.py:308`). That is exactly the shape
this proposal generalizes — the mechanism is proven in-tree, it is just wired to
only one collection and only for text search.

## 3. Design

### 3.1 One side table for every collection

```sql
CREATE TABLE IF NOT EXISTS __beaver_field_index__ (
    kind      TEXT NOT NULL,   -- 'log' | 'doc' | 'dict' | 'list' | 'queue'
                               -- | 'channel' | 'blob' | 'vector' | 'edge'
    name      TEXT NOT NULL,   -- collection name
    item_key  TEXT NOT NULL,   -- the item's identity within its collection
    field     TEXT NOT NULL,   -- dotted path: 'actor_id', 'user.name'
    value     TEXT,            -- normalized scalar
    value_num REAL,            -- same value when numeric (see 3.4)
    PRIMARY KEY (kind, name, item_key, field)
);

CREATE INDEX IF NOT EXISTS idx_field_lookup
    ON __beaver_field_index__ (kind, name, field, value);

CREATE INDEX IF NOT EXISTS idx_field_lookup_num
    ON __beaver_field_index__ (kind, name, field, value_num);
```

One table rather than one per collection: the lookup index carries
`(kind, name)` as its leading columns, so a query never scans another
collection's rows, and cleanup on `clear()` is a single scoped `DELETE`.

### 3.2 The declaration, identical everywhere

```python
db.log("audit",  model=AuditEvent, indexed=["actor_id", "app", "via", "duration_ms"])
db.docs("notes", model=Note,       indexed=["vault_id", "kind"])
db.blob("attachments",             indexed=["owner", "mime"])
db.vectors("chunks",               indexed=["doc_id"])
db.dict("settings",                indexed=["tenant"])
```

`indexed: list[str] | None = None` is added to every collection factory in
`beaver/core.py` (§6 lists them). Dotted paths address nested fields, matching
the `Query.__getattr__` path convention in `beaver/queries.py:17`.

### 3.3 The query surface, identical everywhere

Filters are the existing `Filter` dataclass (`beaver/queries.py:6` — `path`,
`operator`, `value`) built by `q()`, so nothing new is learned:

```python
from beaver import q

await db.log("audit").range(
    where=[q(AuditEvent).actor_id == "alex", q(AuditEvent).duration_ms > 1000],
    order="DESC", limit=50, offset=100,
)

await db.blob("attachments").find(where=[q(Meta).owner == "alex"])

await db.log("audit").aggregate(
    sum="tokens_total", group_by=["actor_id"], where=[q(AuditEvent).app == "magpie"],
)
```

`aggregate(sum=…, count=…, avg=…, min=…, max=…, group_by=[…], where=[…])` lands
on the same surface. Without it, any per-key rollup means summing in Python over
every row — the exact problem this issue exists to remove.

`order` and `offset` are added to `range()`, which has neither today. Absent
them there is no pagination and no newest-first, which is the minimum any log
viewer needs.

### 3.4 Value normalization

Index rows store the scalar twice:

- `value TEXT` — the stringified scalar, for equality and text comparison.
- `value_num REAL` — the same value when it is `int`, `float` or `bool`,
  otherwise `NULL`.

Without `value_num`, `duration_ms > 1000` compares lexicographically and
`"900" > "1000"` is true. Numeric operators resolve against `value_num`;
equality resolves against `value`.

Non-scalar fields (objects, arrays) are **not** indexable. Declaring one raises
at open time rather than silently indexing `"[object]"` — a filter that never
matches is worse than a refusal.

`None` indexes as a row with both columns `NULL`, so `field == None` is
expressible and distinguishable from "field absent".

### 3.5 Completeness manifest — the correctness rule

A new table records what is indexed **and backfilled**:

```sql
CREATE TABLE IF NOT EXISTS __beaver_field_index_manifest__ (
    kind     TEXT NOT NULL,
    name     TEXT NOT NULL,
    field    TEXT NOT NULL,
    complete INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (kind, name, field)
);
```

Query planning per field:

| manifest state | plan |
|---|---|
| `complete = 1` | JOIN `__beaver_field_index__` |
| declared, `complete = 0` | fall back to `json_extract` scan |
| not declared | fall back to `json_extract` scan |

**This rule is what makes the feature safe on an existing database.** An index
that is merely present but not backfilled would return partial results
*silently* — the same failure mode as issue #41, where the danger was never the
error but the silence. A field is trusted only once beaver knows it covered
every row.

Consequences worth stating plainly:

- A query is **always correct**, indexed or not. Only speed varies.
- Adding an index later is an **optimization, not a migration**. Nobody has to
  guess the right field list up front.
- Writes update the index for every declared field, complete or not, so
  `reindex()` only ever has to cover rows written before declaration.

### 3.6 Backfill is explicit

```python
await db.log("audit").reindex()            # all declared fields
await db.log("audit").reindex(["actor_id"])
```

`reindex()` scans the collection once, writes index rows, and sets
`complete = 1` for the fields it covered, in one transaction.

It is **not** run automatically on open. Backfilling a large collection is real
work, and doing it silently inside `connect()` turns an innocuous version bump
into a startup stall on a database the developer did not choose to reindex. On
open, a declaration whose manifest is missing or incomplete is recorded as
declared-and-incomplete, and `reindex()` is left to the consumer.

### 3.7 Index maintenance

Mirroring `_index_trigrams`, in the same transaction as the item write:

| operation | index effect |
|---|---|
| insert / append | insert one row per declared indexed field |
| update / overwrite | delete the item's rows, insert fresh |
| delete / drop | delete the item's rows |
| `clear()` | `DELETE … WHERE kind = ? AND name = ?` |

Batched writes (`AsyncLogBatch`, `AsyncDocumentsBatch`) extend their
`executemany` to cover index rows, so batching keeps its advantage.

## 4. Migration: none

The change is additive by construction and this is a **constraint the
implementation must preserve**, not a happy accident:

1. `_create_all_tables()` runs on **every** `connect()` (`beaver/core.py:222`),
   not only for fresh databases, and every statement is
   `CREATE TABLE IF NOT EXISTS`. An existing database opens and the two new
   tables appear, empty.
2. **No existing table is altered.** No `ALTER TABLE`, no new columns on
   `__beaver_logs__`, `__beaver_documents__` or any other. Existing rows are
   untouched and existing readers are unaffected.
3. **`BEAVER_DB_VERSION` stays at `1`** (`beaver/core.py:42`). `_check_version`
   raises `BeaverIncompatibleSchemaError` when `user_version > BEAVER_DB_VERSION`
   (`beaver/core.py:372`), so bumping it would make a database written by the new
   release **fail to open on the previous release**. Since old code simply
   ignores the new tables, the version must not move — old and new beaver keep
   sharing a file.

If some future requirement cannot fit this shape, the answer is to redesign it
into the side table, not to migrate.

## 5. Costs and trade-offs

- **Write amplification:** one index row per declared field per item write.
  Same order as the existing trigram index, and bounded by an explicit
  declaration rather than by field count.
- **Declared, not automatic:** indexing every field would roughly double the
  write cost of any medium model for filters nobody uses. Declaration keeps the
  cost proportional to intent.
- **Not a replacement for FTS:** this indexes scalars for exact and range
  matching. Substring and relevance search remain FTS5's job in `docs`.
- **Storage:** `__beaver_field_index__` grows with items × declared fields.
  Worth measuring on a large log before recommending wide declarations.
- **Queue identity:** `__beaver_priority_queues__` has no declared PK, so its
  `item_key` is the implicit `rowid`. If a future change rewrites queue rows in
  place, index rows must follow.

## 6. Delivery order

Each slice is independently useful and independently testable.

1. **The substrate.** Both tables, value normalization, the manifest, the shared
   filter→SQL compiler extracted from `docs.py:_execute_query` so `docs` and the
   new consumers cannot drift, and `reindex()`.
2. **`log`** — `indexed=`, plus `where` / `order` / `offset` on `range()`. This
   is the motivating consumer (§7).
3. **`docs`** — route the existing `where()` through the index when the field is
   complete. No API change; `DocumentQuery.where()` keeps working and gets
   faster.
4. **`aggregate()`** on `log` and `docs`.
5. **`blob`, `vectors`, `graphs`** — the `metadata`-column collections, plus a
   `find(where=…)` where none exists.
6. **`dict`, `list`, `queue`, `channel`** — the remaining payload collections.

Slices 1–4 unblock the consumer in §7; 5–6 complete the uniformity promise.

## 7. Motivating consumer

AInBox's suite-wide audit log (`repos/ainbox`, design
`docs/2026-08-01-suite-audit-log-design.md`) records every mutation, every MCP
tool call and every agent turn across seven services, with the resolved user,
elapsed time and token cost on each entry. Its admin page has to filter by user,
app, action, transport and status, search the details, paginate, and aggregate
tokens per user per day.

On today's API that is `range()` with no arguments — the whole log into memory,
filtered in Python (`apps/warden/warden/routes/admin.py:253`). It works for the
few dozen auth entries the log holds now and collapses at the volume the new
design produces.

That consumer needs slices 1, 2 and 4. It is the reason this issue is scoped to
`log` first, but not the reason it is scoped to every collection: the gap is
general, and solving it once per collection type is how it stops recurring.

## 8. Testing

- **Correctness parity:** the same `where` over the same data returns identical
  results indexed and unindexed. Run the whole filter suite twice — once with
  fields declared and reindexed, once with none declared — and assert equality.
  This is the test that keeps the fallback path honest.
- **Incomplete index never lies:** write rows, *then* declare a field, and assert
  queries still return every matching row (fallback), and that `reindex()` does
  not change the result set — only the query plan.
- **Numeric ordering:** `duration_ms > 1000` must exclude `900`. This fails
  without `value_num`, so assert it directly.
- **Maintenance:** update and delete leave no orphan index rows; `clear()` drops
  the collection's rows and no other collection's.
- **Additivity:** open a database created by the previous release, assert it
  opens without error, gains the tables, and that `PRAGMA user_version` is
  unchanged. Then open it again with the previous release and assert *that*
  still works — the guarantee in §4.3 is worthless untested.
- **Batching:** batched writes produce the same index rows as individual ones.

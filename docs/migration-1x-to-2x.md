# Migrating a beaver 1.x database to 2.x

`beaver-db 2.x` renamed every table. 1.x used single-prefix names —
`beaver_dicts`, `beaver_lists`, `beaver_collections`, … — while 2.x uses
dunder names — `__beaver_dicts__`, `__beaver_lists__`, ….

Opening a 1.x database with 2.x is **refused** with `BeaverLegacySchemaError`.
That refusal is deliberate: before it existed, 2.x would open the file without
complaint, report every dict, list and collection as empty, and then create a
fresh dunder table set beside the untouched legacy one. See `issues/41`.

## If you hit `BeaverLegacySchemaError`

**Your data is intact.** Nothing was deleted, moved, or rewritten — 2.x simply
cannot see tables under the old names. Stop writing to the file and migrate it.

There is no automatic migrator yet (see the design below). Today the supported
path is dump-and-load with both versions installed, the same shape as
`migration-rc3-to-rc4-lists.md`: read with `beaver-db==1.3.0`, write the values
out as JSON, then load them into a **new** database opened with 2.x. Do not
load into the legacy file itself.

## If you hit the SPLIT-BRAIN variant

The message names both table sets. This means some earlier 2.x process opened
the 1.x file before this check existed, read empty, and wrote its data into the
dunder tables. The file now holds **two disjoint datasets**:

- the original 1.x data, in `beaver_*`, frozen at the moment of that open;
- everything written since, in `__beaver_*__`.

Neither is a superset of the other. Rolling back to 1.x loses the second;
continuing with 2.x loses the first. Reconciling is an application-level
decision — beaver cannot know which record wins. Take a copy of the file
first, then dump both sides and merge deliberately.

---

## Design: in-place migrator (proposed, NOT implemented)

Status: **design only.** Do not assume this exists.

The legacy tables are ordinary SQLite that 2.x can read directly, so the
dump-and-load dance above is unnecessary in principle. A single-process,
in-place `beaver_*` → `__beaver_*__` migration needs no 1.x install at all.

### Table mapping

Verified by diffing the real 1.x and 2.x schemas on the same file.

**Straight copy** — schemas are byte-identical, so `INSERT INTO __beaver_x__
SELECT * FROM beaver_x` is sufficient:

| 1.x | 2.x |
|---|---|
| `beaver_blobs` | `__beaver_blobs__` |
| `beaver_dicts` | `__beaver_dicts__` |
| `beaver_logs` | `__beaver_logs__` |
| `beaver_priority_queues` | `__beaver_priority_queues__` |
| `beaver_sketches` | `__beaver_sketches__` |
| `beaver_edges` | `__beaver_edges__` |

The `__metadata__` dict row (`beaver_dicts` where `dict_name='__metadata__'`)
carries the 1.x version stamp and must be dropped, not copied.

**Needs transformation:**

- `beaver_lists` → `__beaver_lists__`. The hard case. 1.x `item_order` is a
  `REAL` midpoint scheme; 2.x is a `TEXT` fractional index. Ordering has to be
  regenerated: read each list's rows `ORDER BY item_order`, then walk them
  assigning successive keys via `beaver._fracdex.key_between(prev, None)`.
  This preserves relative order exactly; the numeric values themselves are not
  meaningful and are discarded.
- `beaver_collections` → **splits into two tables**. 1.x fused documents and
  embeddings into `beaver_collections(collection, item_id, item_vector BLOB,
  metadata TEXT)`. 2.x separates them:
  - `__beaver_documents__(collection, item_id, data)` ← rows where
    `metadata IS NOT NULL`;
  - `__beaver_vectors__(collection, item_id, vector, metadata)` ← rows where
    `item_vector IS NOT NULL`.

**Rebuild, do not copy** — these are derived indices, and copying them would
carry a schema mismatch across:

- `beaver_trigrams` → `__beaver_trigrams__`. 1.x has a `field_path` column and
  a different primary key; 2.x does not. Reindex from the migrated documents.
- `beaver_fts_index` → `__beaver_fts_index__`. Same fts5 column list, but an
  fts5 virtual table's shadow tables should be regenerated, not moved.
- LSH: 2.x's `__beaver_lsh_config__` / `__beaver_lsh_index__` have no 1.x
  counterpart and are rebuilt on demand.

**Cannot be migrated — drop with a warning:**

- `beaver_collection_versions`, `beaver_manager_versions` — cache-invalidation
  bookkeeping. Meaningless across the version boundary; start fresh at 0.
- `beaver_vector_change_log` — 1.x incremental-index bookkeeping with no 2.x
  equivalent.
- `beaver_lock_waiters`, `beaver_pubsub_log` — ephemeral runtime state. A lock
  waiter or an undelivered pub/sub message from a dead 1.x process is not
  worth carrying forward.

### Mechanics

Run the whole migration inside one transaction, after `_create_all_tables` has
made the dunder tables, then `DROP TABLE` each legacy table and stamp
`PRAGMA user_version`. If anything raises, the rollback leaves the file exactly
as it was — which is the property that makes in-place safe enough to offer.

Take a file copy first regardless. `VACUUM` afterwards to reclaim the space the
dropped tables held.

### Recommended surface: a CLI subcommand

`beaver migrate <path>` — and **not** an opt-in `BeaverDB(path, migrate=True)`.

Reasons, in order of weight:

1. **A migration is a decision, not a connection option.** It rewrites the file
   irreversibly. Burying that behind a keyword argument on a constructor means
   it can be enabled once in a config file and then fire silently on a
   database nobody meant to touch — the same class of silent-action bug that
   `issues/41` is about. Making a separate command the only path forces an
   explicit, auditable act.
2. **It wants to report.** Rows migrated per table, lists whose ordering was
   regenerated, indices rebuilt, tables dropped. That is a terminal report, not
   something a constructor can return.
3. **The unmigratable parts need to be seen.** Dropping pub/sub backlog and
   lock waiters is fine, but the operator should read that it happened. A
   constructor flag gives nowhere to say it.
4. **`--dry-run` falls out for free**, and is the thing an operator actually
   wants first: report the plan and the row counts, touch nothing.

A standalone script is the weakest option — it has to be found, versioned, and
kept in step with the schema by hand, and the schema knowledge it needs already
lives in the package.

The CLI already exists as the `beaver` entry point (`issues/36`), so this is a
new subcommand rather than new infrastructure. `BeaverLegacySchemaError`'s
message should then name the exact command to run.

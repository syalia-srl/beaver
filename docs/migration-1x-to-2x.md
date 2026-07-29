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

Use the migrator:

```bash
beaver migrate mydata.db --dry-run   # report only; writes nothing
beaver migrate mydata.db             # writes mydata.db.migrated
```

The source is opened **read-only** and is never modified — not even to
checkpoint its WAL. The migrated database is written to a new file, so
adopting it stays an explicit, reversible step:

```bash
mv mydata.db mydata.db.1x-backup
mv mydata.db.migrated mydata.db
```

Keep the backup until you have verified the result. `--dry-run` reports rows
per store, which lists need their ordering regenerated, which indices get
rebuilt, and which tables are dropped and why — it predicts exactly what the
real run does.

### A note on WAL

If the database has an uncheckpointed `-wal` sidecar, its contents *are*
included: SQLite presents main+WAL as one coherent view, and the migrator
reads that view. The dry run reports the WAL's size when one is present.

This matters when you copy a database around: **a copy must carry the `-wal`
file with it.** Copying only the `.db` silently gives you the state as of the
last checkpoint, losing everything still in the WAL.

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

## How the migrator works

Implemented in `beaver/migrate.py`, exposed as `beaver migrate`. It needs no
beaver 1.x install: the legacy tables are ordinary SQLite that 2.x reads
directly.

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

### Encrypted values

Dict values are copied as **opaque TEXT**. A beaver `Secret` field is Fernet
ciphertext in that column, and the salt + verifier live in the `__security__`
dict — which migrates like any other dict. So the migrator never decrypts
anything, needs no key material, and encrypted dicts open afterwards with the
same secret they had before.

### Mechanics

The source is opened read-only (`file:<path>?mode=ro`). A read-only connection
cannot checkpoint, so inspecting a database leaves its main file and `-wal`
byte-identical. Data is written into a freshly created 2.x database inside one
transaction; if anything raises, the destination is incomplete but the source
was never a participant.

There is deliberately **no in-place mode**. Writing beside the original and
leaving the swap to the operator means there is never a moment when a
half-migrated file is the only copy — strictly safer than in-place-with-backup,
and simpler to reason about.

**Split-brain databases are refused, not merged.** Two disjoint datasets is a
judgement about which writes matter, and that is exactly the kind of decision
this tool must not make silently. Dump both sides and reconcile deliberately.

### Surface: a CLI subcommand

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
new subcommand rather than new infrastructure.

### Verified against a real database

The migrator was validated on a production `superbot.db` pulled from the demos
VPS (genuine beaver 1.3.0: 7 dicts, 5 lists, 1 collection, a 4.1 MB
uncheckpointed WAL against a 340 KB main file). All 27 rows migrated, and the
result was read back **through beaver's own API**, not SQL: dict counts match
per store, `conv:*:pairs` lists come back in their original order, the
collection fans out into 3 documents plus 3 384-dimension vectors, and
rebuilt-from-scratch FTS answers `search("Habana")`. The source's main file and
`-wal` were byte-identical afterwards.

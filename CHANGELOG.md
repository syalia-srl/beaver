# Changelog

All notable changes to beaver-db will be recorded here.

## 2.4.2 — 2026-10-30

### Fixed

- **`db.lock()` could admit two waiters at once (#38).** The queue was ordered by a timestamp taken before the waiter's insert, so a waiter that stamped first and inserted second sorted ahead of the holder. The queue is now ordered by `rowid`, the order of arrival. A read-increment-write loop under the lock, 24 increments from 8 threads over two objects on one file, gave a duplicate in 2 of 30 runs on 2.4.1 and in 0 of 100 on 2.4.2.
- **Indexing documents in several batches was quadratic (#40).** Each document's delete scanned the whole FTS5 table. It now finds the rows through a `MATCH` on the id. Three batches of 5,000 short documents took 0.3 s, 25.7 s and 50.4 s on 2.4.1, and about 0.3 s each on 2.4.2. Ids with no tokens, such as `___`, still take the scan.
- **An expired `dict` key was not removed when read.** The delete ran inside the transaction that the `KeyError` rolled back, so the row stayed until it was overwritten.

### Changed

- **Reads no longer write.** `dict.get`, `list.get`, `queue.peek`, `docs.get`, `vectors.get`, `blob.get` and `blob.fetch` took the manager's internal lock, which writes a row to acquire and another to release. They now take only a transaction. `dict.get` went from about 200 to about 700 calls per second through `BeaverDB`.
- **Several processes writing to one manager wait less.** The internal lock polls every 5 ms instead of every 100 ms. Two processes writing to one `dict` went from 22 to 156 writes per second, and four from 21 to 34.

### Corrected

- The 2.4.0 entry said Starlette and uvicorn cancel a request task whenever a client disconnects. In our measurement 12,800 client aborts against a fast plain handler caused no cancellation, while a streaming response was cancelled on every disconnect. The fix stands, and what started the 2026-08-10 outage is not known.

## 2.4.1 — 2026-08-10

### Fixed

- **2.4.0's cleanup could itself hang, and could roll back the wrong
  transaction.** Both were found by exercising a real service over HTTP rather
  than in a unit test, and both come from the same fact: aiosqlite serialises
  every statement onto one worker thread.

  * *The hang.* When a **separate connection** holds the write lock, the
    worker thread is parked inside SQLite's busy handler with `BEGIN
    IMMEDIATE` still running. 2.4.0 *awaited* its cleanup rollback, which
    queued behind that stuck statement — so a caller's 1.5 s deadline became a
    30 s wait for SQLite's busy-timeout. Measured on warden's `/healthz`: curl
    sat through the full 10 s of its `--max-time` and returned nothing.
  * *The wrong rollback.* Merely scheduling it instead is not enough. An
    uncontended `asyncio.Lock.acquire()` does not yield, so the next
    transaction in the same task enqueues its `BEGIN` **ahead** of the pending
    `ROLLBACK` — which then rolls back that innocent transaction, silently
    committing its writes in autocommit.

  Cleanup now runs in a background task that **holds the transaction lock
  until the rollback has landed**. The caller returns immediately, and
  ordering comes from mutual exclusion rather than from scheduling order.
  Waiters are bounded by the same `connection_timeout` as before.

- **Reclaiming an orphaned transaction awaits its rollback**, for the same
  ordering reason — that path continues straight to `BEGIN` without yielding.
  Bounded, and a timeout there raises `TransactionTimeoutError`.

## 2.4.0 — 2026-08-10

### Fixed — availability class

- **A cancelled transaction no longer deadlocks every writer.** `Transaction.
  __aenter__` had two windows in which it could leave `_tx_lock` held with
  `__aexit__` never running, because the `async with` body was never entered:
  cancellation between acquiring the lock and returning, and `BEGIN IMMEDIATE`
  raising. Both left the lock held forever; the cancellation case *also* left
  SQLite's write lock held, because cancelling the wait on
  `connection.execute("BEGIN IMMEDIATE")` does not un-run the statement on
  aiosqlite's worker thread.

  In WAL mode this is nearly invisible: readers keep working while every
  writer queues behind a lock with no owner. It took down authentication on an
  AInBox appliance for hours on 2026-08-10 while the process kept serving its
  login page and passing its healthcheck. Starlette/uvicorn cancel a request
  task whenever a client disconnects, so the trigger is ordinary.

  The enter path now cleans up after itself: a failed or cancelled `BEGIN` is
  rolled back (shielded, so it survives the cancellation that caused it) and
  the lock is released in a `finally`.

- **Ownership is claimed only once the transaction has actually begun.**
  `_tx_owner_task` was set *before* `BEGIN IMMEDIATE`, so a raising BEGIN left
  it naming a transaction that never started — and the reentrancy check then
  waved that task's next transaction through as a silent no-op, so a rolled
  back block would persist.

- **The reentrancy check no longer matches outside a task.**
  `_tx_owner_task == current_task` was true when both were `None`, which
  reads a caller with no running task as already owning the transaction.

### Added

- **`TransactionTimeoutError`** (exported from `beaver`, subclass of
  `TimeoutError`). Waiting for the write lock is now bounded by
  `connection_timeout` (default 30 s) instead of being unbounded. beaver
  multiplexes every modality over a single connection, so contending tasks
  queue on an in-process `asyncio.Lock` that SQLite's busy-timeout — which
  only arbitrates between *separate* connections — never gets a say over.
  An unbounded wait there is indistinguishable from a hang.

- **`db.transaction(timeout=…)`** overrides that bound per call, for callers
  with their own latency budget (a healthcheck, a request handler).

- **An orphaned transaction is reclaimed, not waited on.** If the lock's owner
  is a task that has already finished, the next writer rolls its transaction
  back, logs a warning on the `beaver` logger and takes over. Recovery is
  loud on purpose: it means something leaked.

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

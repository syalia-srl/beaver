---
number: 40
title: "batched() deadlocks under the sync portal on a second large sequential write"
state: open
labels:
- bug
- concurrency
---

### 1. Summary

Under the **sync portal** (`BeaverDB`), performing **two sequential large
`batched()` writes** deadlocks on the second one. The connection hangs with a
`BEGIN IMMEDIATE` transaction held and the aiosqlite worker blocked inside the
SQLite C call; the process never recovers.

It is **size- and sequence-dependent**:

- A single large batch (e.g. 60k docs) — **OK**.
- Two small batches (e.g. 100 + 100) — **OK**.
- Two *large* batches (e.g. 25k + 25k), **same or different collections** — **DEADLOCK** on the second.

The **async engine (`AsyncBeaverDB`) does NOT deadlock** with the identical
sequence — so the bug is in the sync-portal (`BeaverBridge`) × transaction ×
aiosqlite interaction, not in the batch flush SQL itself.

Discovered while bulk-loading a geocoder (~65k FTS docs) via the sync portal.

### 2. Reproduction (minimal)

```python
import tempfile
from beaver import BeaverDB

db = BeaverDB(tempfile.mktemp(suffix=".db"))
col = db.docs("lugares")
body = lambda i: {"nombre": f"Calle {i}", "norm_nombre": f"calle {i}"}

# batch 1 (25k) — completes fine
with col.batched() as b:
    for i in range(25000):
        b.index(id=str(i), body=body(i))

# batch 2 (25k, same collection) — HANGS FOREVER
with col.batched() as b:
    for i in range(25000, 50000):
        b.index(id=str(i), body=body(i))
```

Using two *different* collections for batch 1 and batch 2 deadlocks too.
Reducing both to ~100 items each does not deadlock. A single 60k batch does not
deadlock.

The async form is fine:

```python
import asyncio, tempfile
from beaver.core import AsyncBeaverDB

async def main():
    db = AsyncBeaverDB(tempfile.mktemp(suffix=".db")); await db.connect()
    col = db.docs("lugares")
    async with col.batched() as b:
        for i in range(25000): b.index(id=str(i), body={"nombre": f"c{i}"})
    async with col.batched() as b:                 # no deadlock
        for i in range(25000, 50000): b.index(id=str(i), body={"nombre": f"c{i}"})
    await db.close()

asyncio.run(main())   # completes
```

### 3. Evidence

With `faulthandler.dump_traceback_later(...)` and an `asyncio.all_tasks()` probe
scheduled on the reactor loop while hung on the second batch:

- **Main thread**: blocked in `bridge.py:125 __exit__` → `bridge.py:62 _run` →
  `future.result()` — waiting on the second batch's `__aexit__`.
- **Reactor task**: `Task-7` (the second batch's `__aexit__`) is suspended at
  `docs.py:188` — the `await conn.executemany(...)` (the FTS-delete or a
  subsequent `executemany`) — `wait_for=<Future pending>`.
- **State**: `db._tx_owner_task == Task-7` and `db._tx_lock.locked() == True` —
  i.e. the second batch **holds** the `BEGIN IMMEDIATE` transaction (`core.py`
  `Transaction`) and is stuck inside its `executemany`.
- **aiosqlite worker thread**: blocked at `aiosqlite/core.py:105` `result =
  function()` — i.e. **inside the SQLite C call**, not idle. (aiosqlite 0.21.0.)

So: the second batch acquires the transaction, issues `executemany`, and SQLite
blocks inside the call while the transaction is held — a self-lock the process
cannot break.

### 4. Suspected mechanism

Two things combine:

1. **The sync bridge drives async context managers as *separate tasks*.**
   `BeaverBridge.__enter__` and `__exit__` (`bridge.py:111-125`) each call
   `run_coroutine_threadsafe(...).result()`, so `__aenter__` and `__aexit__` run
   in **different asyncio Tasks**. `Transaction` reentrancy is keyed on
   `asyncio.current_task()` (`core.py:67`, `_tx_owner_task`), which is fragile
   under this pattern.
2. **The batch flush nests two lock layers on the single connection**
   (`docs.py:179-180`): the DB-backed `_internal_lock` (`AsyncBeaverLock`, which
   itself runs polling `BEGIN/SELECT/COMMIT` transactions on the *same*
   connection) wrapping `_db.transaction()` (`BEGIN IMMEDIATE`) held across the
   `executemany`.

The first large batch appears to leave the connection / transaction / advisory
lock in a state where the second large batch's `BEGIN IMMEDIATE` + `executemany`
blocks inside SQLite. The size threshold suggests it is tied to the amount of
work done under the held transaction (WAL growth / checkpoint / busy state)
rather than a pure logic error, but the trigger is the sync-portal task split
above — the async path with identical volume is fine.

### 5. Candidate fixes (need design + regression across warden/magpie)

- **Drop the redundant `_internal_lock` from the batch flush.** `_db.transaction()`
  (`BEGIN IMMEDIATE` + `_tx_lock`) already serializes writers intra-process
  (`_tx_lock`) and inter-process (SQLite RESERVED lock). The nested DB-backed
  advisory lock on the same connection may be both redundant and the trigger.
- **Make the sync bridge drive a whole `with` block in one coroutine/task**, so
  `__aenter__`/body/`__aexit__` share one `asyncio.current_task()` (removes the
  task-identity fragility for `Transaction`).
- **Make `Transaction` reentrancy not depend on task identity** under the portal.

All three touch core machinery shared by every consumer — treat as a v2
stabilization item, not a drive-by patch.

### 6. Workaround

Use **one `batched()` context per collection** (do not chunk a single collection
into multiple sequential batches). A single batch handles tens of thousands of
rows fine. This is what the geocoder does; it blocks safely chunking a very large
(e.g. full-country) load, which is the only scenario that needs the fix.

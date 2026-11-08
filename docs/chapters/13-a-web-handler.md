# A web handler

```{python echo=false output=false}
import glob, os

for f in glob.glob("helpdesk.db*"):
    os.remove(f)
```

The desk gets a web page, served by an async framework (FastAPI, Starlette,
aiohttp). Its handlers run on one event loop, and while one handler waits,
the loop serves the others. Calling the `BeaverDB` of the earlier chapters
from a handler works, but each call blocks the thread until it returns, and
with it the whole loop. Here a handler waits for a ticket's lock that another
process holds, while a second task counts ticks of the loop:

```{python continue}
import asyncio
import threading
import time

from beaver import BeaverDB

sync_db = BeaverDB("helpdesk.db")


def other_agent_holds(seconds):
    with BeaverDB("helpdesk.db") as other, other.lock("claim:T-1301"):
        time.sleep(seconds)


async def ticks(counter, until):
    while time.perf_counter() < until:
        counter.append(1)
        await asyncio.sleep(0.01)


async def handler_sync():
    with sync_db.lock("claim:T-1301", timeout=2):
        return "claimed"


async def page():
    threading.Thread(target=other_agent_holds, args=(0.5,)).start()
    await asyncio.sleep(0.05)
    counter = []
    result, _ = await asyncio.gather(handler_sync(), ticks(counter, time.perf_counter() + 0.6))
    return result, len(counter)


print(asyncio.run(page()))
sync_db.close()
```

The second number counts the ticks in 0.6 seconds. Undisturbed, a loop does
about sixty of them, as the next run shows. Here it only ticked before and
after the half second the lock was held: while the handler waited, no other
request was served.

## The async engine

`AsyncBeaverDB` is the engine `BeaverDB` wraps. It has the same collections
with the same methods, as coroutines: each one is awaited, and waiting yields
the loop to other tasks. Open it with `async with` (or `await db.connect()`
and `await db.close()`).

```{python continue}
from beaver import AsyncBeaverDB


async def handler_async(db):
    async with db.lock("claim:T-1301", timeout=2):
        return "claimed"


async def page():
    async with AsyncBeaverDB("helpdesk.db") as db:
        threading.Thread(target=other_agent_holds, args=(0.5,)).start()
        await asyncio.sleep(0.05)
        counter = []
        result, _ = await asyncio.gather(handler_async(db), ticks(counter, time.perf_counter() + 0.6))
        return result, len(counter)


print(asyncio.run(page()))
```

The loop kept ticking while the handler waited. The collections are the async
classes: `db.dict()` returns an `AsyncBeaverDict`, `db.list()` an
`AsyncBeaverList`, and likewise `AsyncBeaverQueue`, `AsyncBeaverDocuments`,
`AsyncBeaverVectors`, `AsyncBeaverGraph`, `AsyncBeaverBlob`, `AsyncBeaverLog`,
`AsyncBeaverLock`, `AsyncBeaverChannel`, `AsyncBeaverSketch` and
`AsyncBeaverEvents`. What returns many items is an async iterator, for `async
for`, and `batched()` is an `async with`: `AsyncDictBatch`, `AsyncListBatch`,
`AsyncLogBatch`, `AsyncBlobBatch`, `AsyncDocumentsBatch` and `AsyncSketchBatch`.

```{python continue}
async def tour():
    async with AsyncBeaverDB("helpdesk.db") as db:
        owners = db.dict("owners")
        print(type(owners).__name__)
        await owners.set("T-1301", "ana")
        print(await owners.get("T-1301"), await owners.count())
        async with owners.batched() as batch:
            for n in range(3):
                batch[f"T-14{n:02}"] = "luis"
        print([key async for key in owners.keys()])


asyncio.run(tour())
```

`beaver.connect(path, sync=False)` returns an `AsyncBeaverDB` too, not yet
connected.

## Transactions

Each method call is atomic on its own. A handler that changes several things
together wraps them in `async with db.transaction()`: they commit together
at the end of the block, or not at all if it raises.

```{python continue}
async def reassign(db, ticket, agent, fail=False):
    async with db.transaction():
        await db.dict("owners").set(ticket, agent)
        await db.log("audit").log({"ticket": ticket, "action": "reassign", "agent": agent})
        if fail:
            raise RuntimeError("the page closed mid-request")


async def main():
    async with AsyncBeaverDB("helpdesk.db") as db:
        await reassign(db, "T-1301", "luis")
        try:
            await reassign(db, "T-1301", "mia", fail=True)
        except RuntimeError:
            pass
        print(await db.dict("owners").get("T-1301"), await db.log("audit").count())


asyncio.run(main())
```

All the collections of an `AsyncBeaverDB` share one SQLite connection, so a
transaction is a lock on that connection: other tasks that want to write
wait for it to end. That wait is bounded by `connection_timeout` (30 seconds
unless you pass another to `AsyncBeaverDB`), or by `timeout=` on one
transaction, after which it fails with `TransactionTimeoutError`. A handler
with a latency budget passes a short one:

```{python continue}
from beaver import TransactionTimeoutError


async def main():
    async with AsyncBeaverDB("helpdesk.db") as db:

        async def slow_report():
            async with db.transaction():
                await asyncio.sleep(0.5)

        report = asyncio.create_task(slow_report())
        await asyncio.sleep(0.05)
        try:
            async with db.transaction(timeout=0.1):
                pass
        except TransactionTimeoutError as e:
            print("TransactionTimeoutError:", e)
        await report


asyncio.run(main())
```

A `Transaction` is reentrant within a task: a transaction opened inside
another, by the same task, joins it. That is how each atomic method call can
run inside yours.

## Query builders

The documents of chapter 6 have a fluent builder, a `DocumentQuery`, which
from async code is awaited (or iterated with `async for`):

```{python continue}
from beaver import q


async def main():
    async with AsyncBeaverDB("helpdesk.db") as db:
        docs = db.docs("tickets")
        await docs.index(id="T-1501", body={"subject": "Brake rub", "customer": "maria"})
        await docs.index(id="T-1502", body={"subject": "Brake bleed", "customer": "omar"})
        hits = await docs.query().fts("brake").where(q().customer == "maria").limit(5)
        print([h.document.id for h in hits])


asyncio.run(main())
```

## Indexed log fields

A log's `where=` filters scan its entries (chapter 10). The async engine can
declare fields to keep in an index: `db.log(name, indexed=[...])`. Every new
entry then writes those fields' values to a side table. Old entries are not
indexed until `reindex()` backfills them, and until then the index is
declared but not complete, and queries keep scanning, so the answer is never
a partial one. `indexes()` reports each field as a `FieldIndex`, and
`explain()` returns the `QueryPlan`.

```{python continue}
async def main():
    async with AsyncBeaverDB("helpdesk.db") as db:
        audit = db.log("audit", indexed=["agent"])
        for agent in ("ana", "luis", "ana"):
            await audit.log({"agent": agent, "action": "reply"})
        print(await audit.indexes())
        print(await audit.explain([q().agent == "ana"]))
        print(await audit.reindex(), "entries indexed")
        print(await audit.explain([q().agent == "ana"]))
        print(len(await audit.range(where=[q().agent == "ana"])))


asyncio.run(main())
```

Only scalars can be indexed. A declared field holding a dictionary or a list
fails the write with `UnindexableFieldError`:

```{python continue}
from beaver.indexing import UnindexableFieldError


async def main():
    async with AsyncBeaverDB("helpdesk.db") as db:
        try:
            await db.log("audit", indexed=["agent"]).log({"agent": {"name": "ana"}})
        except UnindexableFieldError as e:
            print("UnindexableFieldError:", e)


asyncio.run(main())
```

`BeaverDB.log()` takes no `indexed=` in 2.4, so declaring an index is done
from async code. Once declared, the index is kept by every writer.

## The program

A ticket page handler, as an async function a web framework would call:

```{python export=examples/web_handler.py}
import asyncio

from beaver import AsyncBeaverDB, TransactionTimeoutError


async def claim_and_reply(db: AsyncBeaverDB, ticket: str, agent: str, text: str) -> str:
    try:
        async with db.lock(f"claim:{ticket}", timeout=1):
            owner = await db.dict("owners").fetch(ticket)
            if owner not in (None, agent):
                return f"{ticket} belongs to {owner}"
            async with db.transaction(timeout=2):
                await db.dict("owners").set(ticket, agent)
                await db.list(f"thread:{ticket}").push({"author": agent, "text": text})
                await db.log("audit").log(
                    {"ticket": ticket, "agent": agent, "action": "reply"}
                )
    except (TimeoutError, TransactionTimeoutError):
        return f"{ticket} is busy, try again"
    return f"{agent} replied on {ticket}"


async def main():
    async with AsyncBeaverDB("helpdesk.db") as db:
        await db.dict("owners").clear()
        results = await asyncio.gather(
            claim_and_reply(db, "T-1601", "ana", "On it."),
            claim_and_reply(db, "T-1601", "luis", "Me too."),
        )
        print("\n".join(results))


if __name__ == "__main__":
    asyncio.run(main())
```

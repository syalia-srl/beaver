# One agent per ticket

```{python echo=false output=false}
import glob, os

for f in glob.glob("helpdesk.db*"):
    os.remove(f)
```

The queue gives each ticket to one worker. People work differently: an agent
opens a ticket from the list, and the desk should mark it as theirs so that no
one else answers it too. The obvious version checks whether the ticket has an
owner, and claims it if not.

```{python continue}
import threading
import time

from beaver import BeaverDB

db = BeaverDB("helpdesk.db")


def claim(agent, ticket, results):
    with BeaverDB("helpdesk.db") as own:
        owners = own.dict("owners")
        if ticket not in owners:
            time.sleep(0.05)  # reading the ticket, typing a reply...
            owners[ticket] = agent
            results.append(agent)


results = []
agents = [threading.Thread(target=claim, args=(a, "T-5001", results)) for a in ("ana", "luis")]
for t in agents:
    t.start()
for t in agents:
    t.join()

print("claimed by:", results, "| owner on file:", db.dict("owners")["T-5001"])
```

Both agents saw the ticket free and both believe they own it. Each write is
atomic, but the check and the write are two steps, and the other agent got in
between. The sleep only makes the gap wide enough to hit every time.

## A lock across processes

`db.lock(name)` is a mutual-exclusion lock stored in the database file, so it
holds between threads, processes, and anything else that opens the same file.
Used as a context manager, it waits for the lock, runs the block, and
releases it. Waiters are served in the order they asked.

```{python continue}
def claim(agent, ticket, results):
    with BeaverDB("helpdesk.db") as own:
        owners = own.dict("owners")
        with own.lock(f"claim:{ticket}"):
            if ticket not in owners:
                time.sleep(0.05)
                owners[ticket] = agent
                results.append(agent)


results = []
agents = [threading.Thread(target=claim, args=(a, "T-5002", results)) for a in ("ana", "luis")]
for t in agents:
    t.start()
for t in agents:
    t.join()

print("claimed by:", results)
```

## Not waiting forever

`timeout=` bounds the wait. When it runs out, entering the `with` block
raises `TimeoutError`. To only try, call `acquire(block=False)`, which
returns `False` at once if someone else holds the lock, and `release()` when
done.

```{python continue}
other = BeaverDB("helpdesk.db")

with db.lock("claim:T-5003"):
    try:
        with other.lock("claim:T-5003", timeout=0.2):
            pass
    except TimeoutError as e:
        print("TimeoutError:", e)
    print("try:", other.lock("claim:T-5003").acquire(block=False))

attempt = other.lock("claim:T-5003")
print("after release:", attempt.acquire(block=False))
attempt.release()
```

## When the holder crashes

A process that dies holding a lock never releases it. Every lock has a `ttl`
(60 seconds unless you say otherwise): after that long, the lock counts as
free. A holder that needs longer calls `renew()` before the time is up, which
starts a new `ttl` from now.

```{python continue}
crashed = db.lock("claim:T-5004", ttl=0.3)
crashed.acquire()  # ...and the process dies here
print("held:", other.lock("claim:T-5004").acquire(block=False))
time.sleep(0.4)

survivor = other.lock("claim:T-5004", timeout=1)
print("after ttl:", survivor.acquire())
print("renewed:", survivor.renew(30))
survivor.release()
```

`clear()` removes a lock and everyone waiting on it, for the times an
operator knows the holder is gone and will not wait for the `ttl`.

## Locking a whole collection

Every collection also has a lock of its own. Using a dictionary, list or
queue in a `with` statement holds it, which keeps other processes that do the
same out while you make several changes that belong together. It does not
block plain reads and writes from code that does not take the lock.

```{python continue}
owners = db.dict("owners")
with owners:
    for ticket in ("T-5005", "T-5006", "T-5007"):
        owners[ticket] = "ana"
print({t: owners[t] for t in ("T-5005", "T-5006", "T-5007")})
other.close()
db.close()
```

## The program

Claiming tickets for the desk, as it does from now on:

```{python export=examples/claims.py}
from beaver import BeaverDB


def claim(db: BeaverDB, agent: str, ticket: str) -> bool:
    """Make `agent` the owner of `ticket` unless someone else already is."""
    owners = db.dict("owners")
    with db.lock(f"claim:{ticket}", timeout=5):
        owner = owners.fetch(ticket)
        if owner not in (None, agent):
            return False
        owners[ticket] = agent
        return True


def main():
    with BeaverDB("helpdesk.db") as db:
        db.dict("owners").clear()
        print("ana claims T-6001:", claim(db, "ana", "T-6001"))
        print("luis claims T-6001:", claim(db, "luis", "T-6001"))
        print("owner:", db.dict("owners")["T-6001"])


if __name__ == "__main__":
    main()
```

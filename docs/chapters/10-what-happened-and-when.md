# What happened and when

```{python echo=false output=false}
import glob, os

for f in glob.glob("helpdesk.db*"):
    os.remove(f)
```

A customer complains that nobody answered for two days. The lead wants to
see what happened to the ticket, and later, what the desk did last Tuesday
between two and four. That needs an audit trail: every claim, reply and close,
with the time it happened. A list from chapter 3 can hold it:

```{python continue}
import time

from beaver import BeaverDB

db = BeaverDB("helpdesk.db")
trail = db.list("trail")

now = time.time()
HOUR = 3600
history = [
    (now - 50 * HOUR, "ana", "claim", "T-1001"),
    (now - 49 * HOUR, "ana", "reply", "T-1001"),
    (now - 3 * HOUR, "luis", "reply", "T-1001"),
    (now - 2 * HOUR, "luis", "claim", "T-1002"),
    (now - 1 * HOUR, "ana", "close", "T-1001"),
]
for at, agent, action, ticket in history:
    trail.push({"at": at, "agent": agent, "action": action, "ticket": ticket})

last_day = [e for e in trail if e["at"] > now - 24 * HOUR]
print([(e["agent"], e["action"]) for e in last_day])
```

The question "what happened in this window" reads the whole trail and
filters in Python, so it gets slower every day the desk runs. And the order
of the list is the order of the pushes, which is not the order of events
when two machines report late.

## A log

`db.log(name)` stores entries keyed by their timestamp, and keeps them sorted
by it. `log(data)` adds an entry stamped with the current time, or with the
`timestamp=` you give, in seconds since the epoch. `range(start, end)` returns
the entries in that window, read from the timestamp index, oldest first.

```{python continue}
audit = db.log("audit")
for at, agent, action, ticket in history:
    audit.log({"agent": agent, "action": action, "ticket": ticket}, timestamp=at)

for entry in audit.range(start=now - 24 * HOUR):
    print(round((now - entry.timestamp) / HOUR), "h ago:", entry.data["agent"], entry.data["action"])
```

Each entry is a `LogEntry`, a named tuple of `timestamp` and `data`. `end=`
closes the window, `limit=` caps the number of entries, and `where=` filters
on the data with `q`, as in chapter 6.

```{python continue}
from beaver import q

two_days = audit.range(start=now - 51 * HOUR, end=now - 48 * HOUR)
print([e.data["action"] for e in two_days])
print([e.data["agent"] for e in audit.range(where=[q().ticket == "T-1001", q().action == "reply"])])
print(len(audit.range(limit=2)), audit.count())
```

Two entries cannot share a timestamp. When one collides, `log()` moves the new
one forward by a microsecond and retries, which is invisible at a desk's pace
and can spin under many concurrent writers. `batched()` stamps a batch in
increasing order before it writes, and is the tool for bulk imports.

## Watching it grow

`live()` follows the log from now on: an iterator that never ends, yielding
each new entry as it is written, by this program or any other that has the
file open. It polls every `poll_interval` seconds. Stop it with `break`.

```{python continue}
import threading


def agent_at_work():
    with BeaverDB("helpdesk.db") as other:
        for action in ("claim", "reply", "close"):
            time.sleep(0.1)
            other.log("audit").log({"agent": "mia", "action": action, "ticket": "T-1003"})


threading.Thread(target=agent_at_work).start()

for entry in audit.live(poll_interval=0.05):
    print("live:", entry.data["agent"], entry.data["action"])
    if entry.data["action"] == "close":
        break
db.close()
```

Old entries are not replayed: `live()` starts at the moment it is called.

## Filters on big logs

A `where=` on a log compiles to `json_extract` on every entry in the time
window: correct, and a scan. The async engine (chapter 13) can declare fields
to index on a log, so those filters read an index instead. Sync code can ask
how a filter would run with `explain()`:

```{python continue}
with BeaverDB("helpdesk.db") as db:
    print(db.log("audit").explain([q().agent == "ana"]))
```

A `QueryPlan` lists which filters would use the index and which would scan.
Here nothing is declared, so `agent` scans.

## The program

The desk's audit trail: a helper every other part calls, and the report the
lead asked for.

```{python export=examples/audit.py}
import time

from beaver import BeaverDB, q

HOUR = 3600


def record(db: BeaverDB, agent: str, action: str, ticket: str, at: float | None = None):
    db.log("audit").log(
        {"agent": agent, "action": action, "ticket": ticket}, timestamp=at
    )


def ticket_history(db: BeaverDB, ticket: str) -> list[str]:
    now = time.time()
    return [
        f"{(now - e.timestamp) / HOUR:4.0f} h ago  {e.data['agent']:<5} {e.data['action']}"
        for e in db.log("audit").range(where=[q().ticket == ticket])
    ]


def main():
    with BeaverDB("helpdesk.db") as db:
        db.log("audit").clear()
        now = time.time()
        record(db, "ana", "claim", "T-2001", at=now - 50 * HOUR)
        record(db, "luis", "reply", "T-2001", at=now - 3 * HOUR)
        record(db, "ana", "close", "T-2001", at=now - 1 * HOUR)
        print("\n".join(ticket_history(db, "T-2001")))


if __name__ == "__main__":
    main()
```

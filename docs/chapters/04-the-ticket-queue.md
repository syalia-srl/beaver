# The ticket queue

```{python echo=false output=false}
import glob, os

for f in glob.glob("helpdesk.db*"):
    os.remove(f)
```

New tickets wait until an agent is free. The list from chapter 3 can hold
them: the web form pushes each new ticket at the end, and an agent takes the
first one with `deque()`.

```{python continue}
from beaver import BeaverDB

db = BeaverDB("helpdesk.db")
waiting = db.list("waiting")
waiting.push({"id": "T-2001", "subject": "Which saddle for touring?"})
waiting.push({"id": "T-2002", "subject": "Invoice copy, please"})
waiting.push({"id": "T-2003", "subject": "Brakes failed on a descent", "urgent": True})

print([waiting.deque()["id"] for _ in range(3)])
```

First in, first out. The failed brakes waited behind a saddle question and an
invoice. Keeping two lists, `urgent` and `normal`, works until there are
three levels, and then every agent's loop has to check them in the right
order.

## A priority queue

`db.queue(name)` keeps items ordered by a priority number. `put(item,
priority=...)` adds one, and `get()` removes and returns the item with the
**lowest** priority, the oldest first among equals. Think of the number as a
rank: 1 goes before 2.

```{python continue}
URGENT, NORMAL, LOW = 1, 5, 9

tickets = db.queue("tickets")
tickets.put({"id": "T-2001", "subject": "Which saddle for touring?"}, priority=LOW)
tickets.put({"id": "T-2002", "subject": "Invoice copy, please"}, priority=NORMAL)
tickets.put({"id": "T-2003", "subject": "Brakes failed on a descent"}, priority=URGENT)

item = tickets.get()
print(item)
print(item.data["id"], item.priority)
```

`get()` returns a `QueueItem`, a named tuple with the item's `priority`, the
`timestamp` of its `put` and the `data` itself. `peek()` returns the next one
without removing it, `len()` counts what is waiting, and iterating over the
queue lists the items in order without taking any.

```{python continue}
print(tickets.peek().data["id"], len(tickets))
print([i.data["id"] for i in tickets])
```

## Waiting for work

An agent's loop asks for the next ticket and waits when there is none.
`get()` blocks until an item arrives. With `timeout=` it gives up after that
many seconds with `TimeoutError`, and with `block=False` it raises
`IndexError` at once when the queue is empty.

```{python continue}
tickets.clear()
try:
    tickets.get(timeout=0.2)
except TimeoutError as e:
    print("TimeoutError:", e)
try:
    tickets.get(block=False)
except IndexError as e:
    print("IndexError:", e)
```

## Two workers

The desk runs two workers that answer tickets automatically when they can
(order status, invoice copies). Each one opens its own `BeaverDB` on the same
file, as two processes would. A `get` takes an item out inside one
transaction, so no ticket is handed to both.

```{python continue}
import threading
import time


def worker(name, handled):
    with BeaverDB("helpdesk.db") as own:
        queue = own.queue("tickets")
        while True:
            try:
                item = queue.get(timeout=0.5)
            except TimeoutError:
                return
            handled.append((name, item.data["id"]))
            time.sleep(0.01)


for n in range(20):
    tickets.put({"id": f"T-3{n:03}"}, priority=NORMAL)

handled = []
workers = [threading.Thread(target=worker, args=(w, handled)) for w in ("w1", "w2")]
for w in workers:
    w.start()
for w in workers:
    w.join()

ids = [ticket for _, ticket in handled]
print(len(ids), "handled,", len(set(ids)), "distinct")
print({w: sum(1 for name, _ in handled if name == w) for w in ("w1", "w2")})
db.close()
```

## The program

The desk's intake: the form puts tickets in with a priority from their
subject, and a worker takes them out.

```{python export=examples/ticket_queue.py}
from beaver import BeaverDB

URGENT, NORMAL, LOW = 1, 5, 9
URGENT_WORDS = ("brake", "accident", "injur", "broke")


def priority_for(subject: str) -> int:
    s = subject.lower()
    if any(w in s for w in URGENT_WORDS):
        return URGENT
    return LOW if s.endswith("?") else NORMAL


def submit(db: BeaverDB, ticket: dict) -> None:
    db.queue("tickets").put(ticket, priority=priority_for(ticket["subject"]))


def next_ticket(db: BeaverDB, timeout: float = 1.0) -> dict | None:
    try:
        return db.queue("tickets").get(timeout=timeout).data
    except TimeoutError:
        return None


def main():
    with BeaverDB("helpdesk.db") as db:
        db.queue("tickets").clear()
        submit(db, {"id": "T-4001", "subject": "Which saddle for touring?"})
        submit(db, {"id": "T-4002", "subject": "Invoice copy, please"})
        submit(db, {"id": "T-4003", "subject": "Front brake lever broke"})
        while (ticket := next_ticket(db, timeout=0.1)) is not None:
            print(ticket["id"], ticket["subject"])


if __name__ == "__main__":
    main()
```

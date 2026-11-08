# A ticket's thread

```{python echo=false output=false}
import glob, os

for f in glob.glob("helpdesk.db*"):
    os.remove(f)
```

A ticket is a conversation: the customer's first email, the agent's reply,
the customer's answer, an internal note. Order matters, and a thread only
grows. With a dictionary, the whole thread is one value:

```{python continue}
from beaver import BeaverDB

db = BeaverDB("helpdesk.db")
threads = db.dict("threads")
threads["T-1001"] = [{"from": "customer", "text": "My rear brake squeaks."}]


def reply(handle, ticket, message):
    thread = handle[ticket]
    thread.append(message)
    handle[ticket] = thread


ana = BeaverDB("helpdesk.db").dict("threads")
luis = BeaverDB("helpdesk.db").dict("threads")

first, second = ana["T-1001"], luis["T-1001"]
first.append({"from": "ana", "text": "Can you send a photo?"})
second.append({"from": "luis", "text": "Internal: probably the pads."})
ana["T-1001"] = first
luis["T-1001"] = second

print([m["from"] for m in threads["T-1001"]])
```

It is chapter 1's lost update again, one level down. Two agents read the
thread, each added a message to their copy, and the second save replaced the
first. Each reply also rewrites the whole thread, which gets slower as the
ticket gets longer.

## A list in the file

`db.list(name)` is a list whose items are stored one per row. `push` appends
at the end, and only that item is written, so two agents appending at the
same time both land.

```{python continue}
def thread(handle, ticket):
    return handle.list(f"thread:{ticket}")


ana_db, luis_db = BeaverDB("helpdesk.db"), BeaverDB("helpdesk.db")

thread(db, "T-1001").push({"from": "customer", "text": "My rear brake squeaks."})
thread(ana_db, "T-1001").push({"from": "ana", "text": "Can you send a photo?"})
thread(luis_db, "T-1001").push({"from": "luis", "text": "Internal: probably the pads."})

t = thread(db, "T-1001")
print(len(t), [m["from"] for m in t])
```

A list can take a `model=` as a dictionary can, and the rest of the interface
is a Python list's. Indexes and slices read without loading the rest of the
thread, and negative indexes count from the end:

```{python continue}
print(t[0]["text"])
print([m["from"] for m in t[1:]])
print(t[-1]["text"])
```

`prepend` puts an item first, and `insert(i, item)` puts it before position
`i`. `t[i] = item` replaces one, `del t[i]` removes one, `pop()` takes the
last item off and `deque()` the first. Positions are kept as fractional keys,
so an insert in the middle writes one row and moves nothing.

```{python continue}
t.insert(1, {"from": "bot", "text": "We answer within one working day."})
print([m["from"] for m in t])

note = t.pop()
print("popped:", note["text"])
print([m["from"] for m in t])
```

## Importing a backlog

Moving the desk from the old mailbox means writing a few thousand messages at
once. Each `push` is its own transaction, so a loop of them commits a few
thousand times. `batched()` collects the writes and commits them together
when the `with` block ends.

```{python continue}
import time

old_mail = [{"from": "customer", "text": f"Old message {i}"} for i in range(2000)]

start = time.perf_counter()
for message in old_mail:
    db.list("import:one-by-one").push(message)
one_by_one = time.perf_counter() - start

start = time.perf_counter()
with db.list("import:batched").batched() as batch:
    for message in old_mail:
        batch.push(message)
batched = time.perf_counter() - start

print(len(db.list("import:batched")), "messages")
print(f"batched is {one_by_one / batched:.0f}x faster")
db.close()
```

Every manager that writes many items has a `batched()`: dictionaries
(`batch[key] = value` or `batch.set(...)`), lists (`push`, `prepend`), logs,
blobs, documents and sketches.

## The program

The thread of a ticket, as the desk keeps it from now on:

```{python export=examples/threads.py}
from pydantic import BaseModel

from beaver import BeaverDB


class Message(BaseModel):
    author: str
    text: str
    internal: bool = False


def thread(db: BeaverDB, ticket: str):
    return db.list(f"thread:{ticket}", model=Message)


def public_view(db: BeaverDB, ticket: str) -> list[Message]:
    return [m for m in thread(db, ticket) if not m.internal]


def main():
    with BeaverDB("helpdesk.db") as db:
        t = thread(db, "T-1002")
        t.clear()
        t.push(Message(author="customer", text="The chain skips in 7th gear."))
        t.push(Message(author="luis", text="Check cable tension.", internal=True))
        t.push(Message(author="ana", text="Bring it in, we'll adjust it for free."))
        for m in public_view(db, "T-1002"):
            print(f"{m.author}: {m.text}")


if __name__ == "__main__":
    main()
```

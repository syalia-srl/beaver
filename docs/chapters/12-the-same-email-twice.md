# The same email twice

```{python echo=false output=false}
import glob, os

for f in glob.glob("helpdesk.db*"):
    os.remove(f)
```

The desk reads the support mailbox every minute, and a mail server
sometimes delivers the same message twice. Each email has a `Message-ID`
header, so the reader remembers the ids it has turned into tickets and skips
the ones it has seen. A dictionary of ids does that exactly:

```{python continue}
import os

from beaver import BeaverDB

db = BeaverDB("helpdesk.db")
seen = db.dict("seen-ids")

with seen.batched() as batch:
    for n in range(50_000):
        batch[f"<{n}.support@mail.example>"] = True

print("<17.support@mail.example>" in seen, "<new@mail.example>" in seen)
db.close()
print(f"{os.path.getsize('helpdesk.db') / 1e6:.1f} MB for {50_000:,} ids")
```

It grows with every email, forever. A busy shop's mailbox runs to millions of
messages, and the table that only answers "seen it?" becomes the largest one
in the file. The other question the desk asks, how many distinct customers
wrote this month, needs a set of addresses that grows the same way.

## Sketches

`db.sketch(name)` is an approximate set with a fixed size. It answers two
questions: whether an item was added (a Bloom filter), and about how many
distinct items were added (a HyperLogLog). Its size is set by the
`capacity` and the `error_rate` you ask for, not by what you add. Both
structures live in one `ApproximateSet`, stored as a single blob in the file.

```{python continue}
os.remove("helpdesk.db")
db = BeaverDB("helpdesk.db")
ids = db.sketch("seen-ids", capacity=1_000_000, error_rate=0.01)

with ids.batched() as batch:
    for n in range(50_000):
        batch.add(f"<{n}.support@mail.example>")

print("<17.support@mail.example>" in ids, "<new@mail.example>" in ids)
print(len(ids), "distinct, approximately")
db.close()
print(f"{os.path.getsize('helpdesk.db') / 1e6:.1f} MB, for up to 1,000,000 ids")
```

The file is the same size at fifty thousand ids and at a million. The price
is the error rate. "Not seen" is always right, and "seen" is wrong for about
1 in 100 items never added, when the sketch is full. The count is off by a
fraction of a percent. For the mailbox that means about one new email in a
hundred mistaken for a duplicate, at a million ids. A desk that cannot
afford that checks the sketch first and the exact record only when the
sketch says "seen", which is rare.

```{python continue}
with BeaverDB("helpdesk.db") as db:
    ids = db.sketch("seen-ids", capacity=1_000_000, error_rate=0.01)
    wrong = sum(f"<other-{n}@mail.example>" in ids for n in range(5_000))
    print(wrong, "false positives in 5,000 ids never added")
```

At fifty thousand ids the sketch is far from full, so the rate measured here
is well under the 1% it guarantees at capacity.

## What a sketch remembers

The capacity and error rate are fixed when the sketch is created. Opening it
again with other values is an error, since the bits would mean something
else:

```{python continue}
with BeaverDB("helpdesk.db") as db:
    try:
        db.sketch("seen-ids", capacity=10_000).add("<x@mail.example>")
    except ValueError as e:
        print("ValueError:", e)
```

`add` and `batched()` write to the file, and the next `BeaverDB` that opens
the sketch sees those items. `contains` (and `in`) reads the copy this
`BeaverDB` loaded, which is refreshed by its own next `add`. So in a program
that only checks, items another process added since appear after its next
`add`, or after reopening. The mailbox reader is the only writer of its
sketch, which keeps it simple. A sketch keeps no items, so it cannot list
what it holds, and nothing can be removed from it except everything, with
`clear()`.

## The program

The mailbox reader: skip what was seen, count the distinct senders.

```{python export=examples/mailbox.py}
from beaver import BeaverDB


def read_mailbox(db: BeaverDB, emails: list[dict]) -> list[str]:
    seen = db.sketch("seen-ids", capacity=1_000_000, error_rate=0.01)
    senders = db.sketch("senders", capacity=100_000, error_rate=0.01)
    new_tickets = []
    for email in emails:
        if email["message_id"] in seen:
            continue
        seen.add(email["message_id"])
        senders.add(email["from"])
        new_tickets.append(email["subject"])
    return new_tickets


def main():
    with BeaverDB("helpdesk.db") as db:
        db.sketch("seen-ids", capacity=1_000_000, error_rate=0.01).clear()
        db.sketch("senders", capacity=100_000, error_rate=0.01).clear()
        inbox = [
            {"message_id": "<1@mail.example>", "from": "maria@example.com", "subject": "Brakes"},
            {"message_id": "<2@mail.example>", "from": "omar@example.com", "subject": "Chain"},
            {"message_id": "<1@mail.example>", "from": "maria@example.com", "subject": "Brakes"},
        ]
        print("new tickets:", read_mailbox(db, inbox))
        print("distinct senders:", len(db.sketch("senders", capacity=100_000, error_rate=0.01)))


if __name__ == "__main__":
    main()
```

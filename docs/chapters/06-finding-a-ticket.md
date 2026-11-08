# Finding a ticket

```{python echo=false output=false}
import glob, os

for f in glob.glob("helpdesk.db*"):
    os.remove(f)
```

A customer phones: "I wrote last week about my brakes". The agent needs the
ticket, and all they have is a word and a name. With the tickets in a
dictionary, the search is a loop:

```{python continue}
from beaver import BeaverDB

db = BeaverDB("helpdesk.db")
tickets = db.dict("tickets")
tickets["T-7001"] = {"subject": "Rear brake squeaks", "text": "It squeaks every time I stop.", "customer": "maria", "age_days": 6}
tickets["T-7002"] = {"subject": "Chain skips", "text": "The chain skips in 7th gear after braking hard.", "customer": "omar", "age_days": 2}
tickets["T-7003"] = {"subject": "New pads?", "text": "Do you stock brake pads for hydraulic discs?", "customer": "maria", "age_days": 1}
tickets["T-7004"] = {"subject": "Invoice", "text": "Please send a copy of my invoice.", "customer": "lena", "age_days": 9}


def find(word):
    return [k for k, t in tickets.items() if word in t["subject"] + " " + t["text"]]


print(find("brake"), find("Brake"), find("brakes"), find("brkae"))
```

Case matters, `brakes` finds nothing because no ticket says it, and a typo
finds nothing at all. The results come in file order rather than best match
first. And every search reads every ticket, which is fine for four and not
for forty thousand.

## Documents and full-text search

`db.docs(name)` is a collection of documents built for searching. `index()`
stores a document under an id and adds every string field in it, nested ones
included, to an SQLite FTS5 index. `search(text)` returns the matches,
best first.

```{python continue}
docs = db.docs("tickets")
for ticket_id, ticket in tickets.items():
    docs.index(id=ticket_id, body=ticket)

for hit in docs.search("brake"):
    print(hit.document.id, hit.document.body["subject"], round(hit.score, 3))
```

Each result is a `ScoredDocument`: the `Document` itself (its `id` and
`body`) and a `score`. For full-text search the score is SQLite's BM25 rank,
where lower is better, so the numbers are negative and the first result has
the lowest. The index is case-insensitive and stems words to their root, so
`brake` also found the ticket that says "braking", and `brakes` finds the same
three. `on=` restricts the search to some fields:

```{python continue}
print([h.document.id for h in docs.search("brakes")])
print([h.document.id for h in docs.search("brake", on=["subject"])])
print([h.document.id for h in docs.search("brake pads")])
```

Several words must all appear. FTS5 reads some punctuation as query syntax,
so a customer's words go through a small cleanup before they reach
`search()`. Without it, a question mark is an error:

```{python continue}
import re

try:
    docs.search("pads?")
except Exception as e:
    print(type(e).__name__, e)


def words(text):
    return " ".join(re.findall(r"\w+", text))


print([h.document.id for h in docs.search(words("pads?"))])
```

A hyphen is the worst case: FTS5 reads `a-b` as "column `a` without `b`" and
fails with `no such column`, which says nothing about punctuation.

## Typos

Full-text search matches words exactly. Fuzzy search compares the three-letter
pieces (trigrams) of the query with those of the documents, so it tolerates a
typo. It needs trigrams computed when the document is indexed, with
`fuzzy=True`, and is then asked for with `search(text, fuzzy=True)`.

```{python continue}
print("not indexed for fuzzy:", docs.search("brkae squeks", fuzzy=True))

for ticket_id, ticket in tickets.items():
    docs.index(id=ticket_id, body=ticket, fuzzy=True)

for hit in docs.search("brake squeks", fuzzy=True):
    print(hit.document.id, hit.document.body["subject"], hit.score)
```

For fuzzy results the score counts shared trigrams, so here higher is better.

## Filters

The customer's name is not a word to search for but a field to match.
`where=` takes conditions written with `q`: `q()` starts a path into the
document, attribute access extends it (`q().customer`, or `q().address.city`
for a nested field), and a comparison (`==`, `!=`, `<`, `<=`, `>`, `>=`) turns
it into a `Filter`. `sort=` orders by a field, and `limit=` and `offset=` page
through the results.

```{python continue}
from beaver import q

print([h.document.id for h in docs.search("brake", where=[q().customer == "maria"])])

recent = docs.search(where=[q().age_days <= 6], sort={"age_days": "ASC"}, limit=2)
print([(h.document.id, h.document.body["age_days"]) for h in recent])
```

`q("customer")` builds the same path from a string, and `q(Ticket)` starts it
from a pydantic model class, which lets a type checker see the field names.
Filters compile to `json_extract` on every candidate row: fast, but a scan,
so on a large collection combine them with a text query that narrows the rows
first. The collection also has `get(id)`, `get_many(ids)`, `drop(id)`,
`count()` and iteration over its documents.

```{python continue}
print(docs.get("T-7004").body["subject"], [d.id for d in docs.get_many(["T-7001", "T-7003"])])
docs.drop("T-7004")
print(docs.count(), [d.id for d in docs])
db.close()
```

The collection also has a fluent builder, `docs.query().fts(...).where(...)`,
but from `BeaverDB` it returns the async builder unwrapped, so its results
cannot be read (issue #46). Chapter 13 uses it from async code, where it
works. From sync code, `search()` with keyword arguments does the same.

## The program

The desk's ticket search, typed with a model:

```{python export=examples/ticket_search.py}
import re

from pydantic import BaseModel

from beaver import BeaverDB, q


class Ticket(BaseModel):
    subject: str
    text: str
    customer: str
    age_days: int


def words(text: str) -> str:
    return " ".join(re.findall(r"\w+", text))


def find(db: BeaverDB, text: str, customer: str | None = None) -> list[str]:
    docs = db.docs("tickets", model=Ticket)
    where = [q(Ticket).customer == customer] if customer else None
    hits = docs.search(words(text), where=where, limit=10)
    if not hits:
        hits = docs.search(text, fuzzy=True, where=where, limit=10)
    return [h.document.id for h in hits]


def main():
    with BeaverDB("helpdesk.db") as db:
        docs = db.docs("tickets", model=Ticket)
        docs.clear()
        for id, subject, text, customer, age in [
            ("T-8001", "Rear brake squeaks", "It squeaks when I stop.", "maria", 6),
            ("T-8002", "Brake pads?", "Do you stock pads for discs?", "maria", 1),
            ("T-8003", "Invoice", "Please send my invoice.", "lena", 9),
        ]:
            ticket = Ticket(subject=subject, text=text, customer=customer, age_days=age)
            docs.index(id=id, body=ticket, fuzzy=True)
        print("brake, maria:", find(db, "brake", customer="maria"))
        print("invoce (typo):", find(db, "invoce"))


if __name__ == "__main__":
    main()
```

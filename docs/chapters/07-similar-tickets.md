# Similar tickets

```{python echo=false output=false}
import glob, os

for f in glob.glob("helpdesk.db*"):
    os.remove(f)
```

When a new ticket comes in, the agent wants the old tickets that were about
the same problem, and how they were solved. Full-text search needs shared
words. "Brakes squeal when stopping" and "noise from the back wheel when I
slow down" share none, and they are the same problem.

The usual answer is embeddings: a model turns each text into a vector so that
texts with similar meaning get nearby vectors. Real ones come from a model
such as sentence-transformers or an embeddings API. To keep this chapter
self-contained it uses a stand-in: the first five letters of each word that
is not a stop word, hashed into 256 numbers. It only knows shared word stems, but the vectors behave like real ones: you store
them, and you look for the nearest.

```{python continue}
import hashlib
import re

import numpy as np


STOP = {"my", "the", "a", "in", "for", "when", "i", "lot", "from", "last"}


def embed(text, dim=256):
    v = np.zeros(dim, dtype=np.float32)
    for word in re.findall(r"\w+", text.lower()):
        if word not in STOP:
            # The first five letters stand in for meaning: brake, brakes, braking.
            v[int(hashlib.md5(word[:5].encode()).hexdigest(), 16) % dim] += 1
    norm = np.linalg.norm(v)
    return (v / norm if norm else v).tolist()


old_tickets = {
    "T-9001": "Rear brake squeaks when stopping",
    "T-9002": "Chain skips in seventh gear",
    "T-9003": "Front brake squeaks loudly in the rain",
    "T-9004": "Invoice copy for my last order",
    "T-9005": "Gear cable snapped",
}
```

With what we have, the vectors go in a dictionary and the search compares
the query with every one of them:

```{python continue}
from beaver import BeaverDB

db = BeaverDB("helpdesk.db")
by_id = db.dict("embeddings")
for ticket_id, text in old_tickets.items():
    by_id[ticket_id] = embed(text)


def nearest(text, k=2):
    query = np.array(embed(text))
    scored = [(1 - float(np.dot(query, v)), tid) for tid, v in by_id.items()]
    return sorted(scored)[:k]


print(nearest("my brakes squeak"))
```

It works, and every search reads every vector out of the file as JSON and
compares them one at a time in Python. At a few thousand tickets that is
already the slow part of the request.

## A vector collection

`db.vectors(name)` stores vectors as packed float32 arrays, each with an id
and optional metadata. `near(vector, k=...)` returns the `k` closest ones,
computed with numpy over the whole collection at once.

```{python continue}
vectors = db.vectors("tickets")
for ticket_id, text in old_tickets.items():
    customer = "maria" if ticket_id in ("T-9001", "T-9004") else "omar"
    vectors.set(ticket_id, embed(text), {"customer": customer, "text": text})

for item in vectors.near(embed("my brakes squeak"), k=2):
    print(item.id, round(item.score, 3), item.metadata["text"])
```

Each result is a `VectorItem` with the `id`, the `vector`, the `metadata` and
a `score`. The default score is the cosine similarity mapped to a distance
between 0 and 1, `(1 - cos) / 2`: 0 is the same direction, 0.5 unrelated, and
lower means closer. It is half the `1 - cos` the loop above computed. `get(id)`,
`delete(id)`, `len()` and iteration work as in the other collections.

## Narrowing the search

`filters=` takes the same `q` conditions as chapter 6, applied to the
metadata. `candidate_ids=` restricts the search to a list of ids, for example
the result of a full-text search, which is how you combine the two kinds of
search.

```{python continue}
from beaver import q

print([i.id for i in vectors.near(embed("squeaky brakes"), k=3, filters=[q().customer == "omar"])])
print([i.id for i in vectors.near(embed("squeaky brakes"), k=3, candidate_ids=["T-9002", "T-9005"])])
```

`metric=` replaces the cosine distance with any function that takes the
matrix of stored vectors and the query and returns one score per row, lower
being better. Euclidean distance, for instance:

```{python continue}
def euclidean(matrix, query):
    return np.linalg.norm(matrix - query, axis=1)


print([(i.id, round(i.score, 3)) for i in vectors.near(embed("squeaky brakes"), k=2, metric=euclidean)])
```

## Many vectors

Comparing with every vector is exact, and fine up to some thousands. Past
10,000 vectors in a collection, `near()` switches to an index: each vector is
hashed into a 16-bit bucket by random hyperplanes (SimHash), and the search
only scores the vectors in the query's bucket and the 16 buckets one bit away.
It is faster and approximate: a close vector that hashed far away is missed.
`method="exact"` or `method="lsh"` picks one regardless of size.

```{python continue}
print([i.id for i in vectors.near(embed("squeaky brakes"), k=2, method="lsh")])
db.close()
```

The index is pure numpy, like the rest of beaver, so there is nothing
compiled to install.

## The program

Suggesting similar solved tickets for a new one. Swap `embed` for a real
model and nothing else changes.

```{python export=examples/similar_tickets.py}
import hashlib
import re

import numpy as np

from beaver import BeaverDB, q


STOP = {"my", "the", "a", "in", "for", "when", "i", "lot", "from", "last"}


def embed(text: str, dim: int = 256) -> list[float]:
    """A stand-in for a real embedding model: hashed bag of word stems."""
    v = np.zeros(dim, dtype=np.float32)
    for word in re.findall(r"\w+", text.lower()):
        if word not in STOP:
            v[int(hashlib.md5(word[:5].encode()).hexdigest(), 16) % dim] += 1
    norm = np.linalg.norm(v)
    return (v / norm if norm else v).tolist()


def remember(db: BeaverDB, ticket_id: str, text: str, solved: bool) -> None:
    db.vectors("tickets").set(ticket_id, embed(text), {"text": text, "solved": solved})


def similar_solved(db: BeaverDB, text: str, k: int = 3) -> list[str]:
    hits = db.vectors("tickets").near(embed(text), k=k, filters=[q().solved == True])
    return [h.metadata["text"] for h in hits if h.score < 0.4]


def main():
    with BeaverDB("helpdesk.db") as db:
        db.vectors("tickets").clear()
        remember(db, "T-9101", "Rear brake squeaks when stopping", solved=True)
        remember(db, "T-9102", "Chain skips in seventh gear", solved=True)
        remember(db, "T-9103", "Front brake squeaks in the rain", solved=False)
        for text in similar_solved(db, "brakes squeak a lot"):
            print("see:", text)


if __name__ == "__main__":
    main()
```

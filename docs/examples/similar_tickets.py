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

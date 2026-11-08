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

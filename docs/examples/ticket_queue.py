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

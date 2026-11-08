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

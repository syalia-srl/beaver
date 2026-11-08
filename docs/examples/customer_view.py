from beaver import BeaverDB


def record_order(db: BeaverDB, customer: str, order: str) -> None:
    db.graph("desk").link(customer, order, "ordered")


def record_ticket(db: BeaverDB, order: str, ticket: str) -> None:
    db.graph("desk").link(order, ticket, "about")


def escalate(db: BeaverDB, ticket: str, desk: str, case: str) -> None:
    db.graph("desk").link(ticket, desk, "escalated", {"case": case})


def customer_view(db: BeaverDB, customer: str) -> list[str]:
    g = db.graph("desk")
    lines = []
    for order in g.children(customer, label="ordered"):
        for ticket in g.children(order, label="about"):
            escalations = [e for e in g.edges(ticket) if e.label == "escalated"]
            note = "".join(
                f" (escalated to {e.target}, case {e.metadata['case']})"
                for e in escalations
            )
            lines.append(f"{order} / {ticket}{note}")
    return lines


def main():
    with BeaverDB("helpdesk.db") as db:
        db.graph("desk").clear()
        record_order(db, "maria", "O-501")
        record_ticket(db, "O-501", "T-1001")
        record_ticket(db, "O-501", "T-1002")
        escalate(db, "T-1001", "warranty:shimano", "SH-7781")
        for line in customer_view(db, "maria"):
            print(line)


if __name__ == "__main__":
    main()

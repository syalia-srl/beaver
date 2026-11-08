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

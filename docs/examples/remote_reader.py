import os

from beaver import connect


def open_desk():
    url = os.environ.get("BEAVER_URL", "helpdesk.db")
    return connect(url, api_key=os.environ.get("BEAVER_API_KEY"))


def import_email(desk, ticket: str, subject: str, urgent: bool) -> None:
    desk.queue("tickets").put(
        {"id": ticket, "subject": subject}, priority=1 if urgent else 5
    )
    desk.log("audit").log({"agent": "mailbox", "action": "import", "ticket": ticket})


def main():
    desk = open_desk()
    try:
        desk.queue("tickets").clear()
        import_email(desk, "T-1801", "Brakes failed", urgent=True)
        import_email(desk, "T-1802", "Invoice copy", urgent=False)
        print(type(desk).__name__, "queue:", len(desk.queue("tickets")))
    finally:
        desk.close()


if __name__ == "__main__":
    main()

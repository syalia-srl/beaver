import threading
import time

from beaver import BeaverDB


def raise_alert(db: BeaverDB, ticket: str, subject: str) -> None:
    db.channel("alerts").publish({"id": ticket, "subject": subject})


def agent_screen(db: BeaverDB, stop_after: int) -> None:
    alerts = db.channel("alerts")
    for m in alerts.history(limit=5):
        print("missed:", m.payload["id"], m.payload["subject"])
    for n, m in enumerate(alerts.listen(), start=1):
        print("new:   ", m.payload["id"], m.payload["subject"])
        if n == stop_after:
            return


def main():
    with BeaverDB("helpdesk.db") as db:
        db.channel("alerts").clear()
        raise_alert(db, "T-1201", "Brakes failed")

        def form():
            time.sleep(0.3)
            raise_alert(db, "T-1202", "Crash, wheel bent")

        threading.Thread(target=form).start()
        agent_screen(db, stop_after=1)


if __name__ == "__main__":
    main()

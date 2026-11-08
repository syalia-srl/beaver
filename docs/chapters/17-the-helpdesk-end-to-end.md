# The helpdesk, end to end

```{python echo=false output=false}
import glob, os

for f in glob.glob("helpdesk.db*"):
    os.remove(f)
```

This chapter puts the desk together as one program, built only from what the
earlier chapters introduced. It reads a mailbox, turns new emails into
tickets, lets an agent sign in, take the most urgent ticket, look up related
ones and reply, and keeps the audit trail. Everything lives in one file.

The records first: an agent with a hashed password (chapter 2), a ticket
(chapter 6) and a message of its thread (chapter 3).

```{python export=examples/helpdesk.py}
import glob
import os
import re
import secrets

from pydantic import BaseModel

from beaver import BeaverDB, Secret, q

URGENT, NORMAL, LOW = 1, 5, 9


class Agent(BaseModel):
    name: str
    password: Secret


class Ticket(BaseModel):
    subject: str
    text: str
    customer: str
    status: str = "open"


class Message(BaseModel):
    author: str
    text: str
```

Intake. The mailbox reader skips emails it has seen with a sketch (chapter
12), indexes each new ticket for search (chapter 6), starts its thread
(chapter 3), puts it in the queue with a priority (chapter 4), links it to the
customer (chapter 8) and logs it (chapter 10).

```{python export=examples/helpdesk.py continue}


def priority_for(subject: str) -> int:
    s = subject.lower()
    if any(w in s for w in ("brake", "crash", "broke")):
        return URGENT
    return LOW if s.endswith("?") else NORMAL


def intake(db: BeaverDB, emails: list[dict]) -> list[str]:
    seen = db.sketch("seen-ids", capacity=100_000, error_rate=0.01)
    created = []
    for email in emails:
        if email["message_id"] in seen:
            continue
        seen.add(email["message_id"])
        ticket_id = f"T-{db.dict('counters').fetch('ticket', 1000) + 1}"
        db.dict("counters")["ticket"] = int(ticket_id[2:])
        ticket = Ticket(
            subject=email["subject"], text=email["text"], customer=email["from"]
        )
        db.docs("tickets", model=Ticket).index(id=ticket_id, body=ticket, fuzzy=True)
        db.list(f"thread:{ticket_id}", model=Message).push(
            Message(author=email["from"], text=email["text"])
        )
        db.queue("tickets").put(ticket_id, priority=priority_for(email["subject"]))
        db.graph("desk").link(email["from"], ticket_id, "wrote")
        db.log("audit").log({"agent": "mailbox", "action": "open", "ticket": ticket_id})
        created.append(ticket_id)
    return created
```

Agents sign in and get a session that expires (chapter 2). Taking the next
ticket claims it under a lock (chapters 4 and 5), and a reply goes to the
thread, the audit trail and the live channel (chapter 11).

```{python export=examples/helpdesk.py continue}


def add_agent(db: BeaverDB, login: str, name: str, password: str) -> None:
    db.dict("accounts", model=Agent)[login] = Agent(
        name=name, password=Secret(password)
    )


def sign_in(db: BeaverDB, login: str, password: str) -> str | None:
    agent = db.dict("accounts", model=Agent).fetch(login)
    if agent is None or agent.password != password:
        return None
    token = secrets.token_hex(16)
    db.dict("sessions").set(token, login, ttl_seconds=8 * 3600)
    return token


def take_next(db: BeaverDB, token: str) -> str | None:
    login = db.dict("sessions").fetch(token)
    if login is None:
        raise PermissionError("session expired")
    try:
        ticket_id = db.queue("tickets").get(timeout=0.1).data
    except TimeoutError:
        return None
    with db.lock(f"claim:{ticket_id}", timeout=5):
        db.dict("owners")[ticket_id] = login
    db.log("audit").log({"agent": login, "action": "claim", "ticket": ticket_id})
    return ticket_id


def reply(
    db: BeaverDB, token: str, ticket_id: str, text: str, close: bool = False
) -> None:
    login = db.dict("sessions")[token]
    db.list(f"thread:{ticket_id}", model=Message).push(Message(author=login, text=text))
    db.log("audit").log({"agent": login, "action": "reply", "ticket": ticket_id})
    if close:
        docs = db.docs("tickets", model=Ticket)
        ticket = docs.get(ticket_id).body
        ticket.status = "closed"
        docs.index(id=ticket_id, body=ticket, fuzzy=True)
        db.channel("desk").publish(
            {"ticket": ticket_id, "event": "closed", "by": login}
        )
```

Looking things up: the customer's other tickets through the graph (chapter
8), a search with a typo fallback (chapter 6), and a ticket's history from the
audit trail (chapter 10).

```{python export=examples/helpdesk.py continue}


def other_tickets(db: BeaverDB, ticket_id: str) -> list[str]:
    g = db.graph("desk")
    customers = list(g.parents(ticket_id, label="wrote"))
    return [
        t for c in customers for t in g.children(c, label="wrote") if t != ticket_id
    ]


def search(db: BeaverDB, text: str, status: str = "open") -> list[str]:
    docs = db.docs("tickets", model=Ticket)
    where = [q(Ticket).status == status]
    hits = docs.search(" ".join(re.findall(r"\w+", text)), where=where)
    hits = hits or docs.search(text, fuzzy=True, where=where)
    return [h.document.id for h in hits]


def history(db: BeaverDB, ticket_id: str) -> list[str]:
    entries = db.log("audit").range(where=[q().ticket == ticket_id])
    return [f"{e.data['agent']} {e.data['action']}" for e in entries]
```

And a morning at the desk:

```{python export=examples/helpdesk.py continue}


MAILBOX = [
    {
        "message_id": "<a1@mail>",
        "from": "maria",
        "subject": "Which saddle for touring?",
        "text": "Looking for a comfortable saddle.",
    },
    {
        "message_id": "<a2@mail>",
        "from": "omar",
        "subject": "Front brake broke",
        "text": "The lever snapped on a descent.",
    },
    {
        "message_id": "<a1@mail>",
        "from": "maria",
        "subject": "Which saddle for touring?",
        "text": "Looking for a comfortable saddle.",
    },
    {
        "message_id": "<a3@mail>",
        "from": "maria",
        "subject": "Invoice copy",
        "text": "Please send the invoice for my saddle.",
    },
]


def main():
    # The demo starts from an empty desk of its own.
    for f in glob.glob("helpdesk-demo.db*"):
        os.remove(f)
    with BeaverDB("helpdesk-demo.db") as db:
        print("opened:", intake(db, MAILBOX))

        add_agent(db, "ana", "Ana", "correct-horse")
        print("wrong password:", sign_in(db, "ana", "guess"))
        token = sign_in(db, "ana", "correct-horse")

        first = take_next(db, token)
        print(
            "ana takes:",
            first,
            db.docs("tickets", model=Ticket).get(first).body.subject,
        )
        reply(db, token, first, "Please don't ride it, bring it in today.", close=True)

        print("search 'sadle':", search(db, "sadle"))
        maria_ticket = search(db, "saddle")[0]
        print("maria's other tickets:", other_tickets(db, maria_ticket))
        print("history of", first, history(db, first))
        print("still queued:", len(db.queue("tickets")))


if __name__ == "__main__":
    main()
```


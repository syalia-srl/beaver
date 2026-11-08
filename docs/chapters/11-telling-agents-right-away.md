# Telling agents right away

```{python echo=false output=false}
import glob, os

for f in glob.glob("helpdesk.db*"):
    os.remove(f)
```

When an urgent ticket arrives, every agent's screen should show it at once,
not at the next refresh. Without anything new, each agent's program asks the
database every few seconds whether something changed:

```{python continue}
import threading
import time

from beaver import BeaverDB

db = BeaverDB("helpdesk.db")
inbox = db.list("inbox")


def form():
    with BeaverDB("helpdesk.db") as other:
        time.sleep(0.2)
        other.list("inbox").push({"id": "T-1101", "subject": "Brakes failed"})


threading.Thread(target=form).start()

seen, checks, start = 0, 0, time.perf_counter()
while True:
    checks += 1
    if len(inbox) > seen:
        print(f"noticed {inbox[-1]['id']} after {checks} checks, {time.perf_counter() - start:.1f} s")
        break
    time.sleep(1.0)
```

A one-second poll noticed the ticket up to a second late, and a desk of
twenty agents asks twenty times a second for nothing most of the day. A
shorter interval is faster and costs more. And every program has to remember
what it already saw.

## Channels

`db.channel(name)` is a publish-subscribe channel kept in the file.
`publish(message)` sends a message to everyone listening, in this program or
in any other that has the file open. `listen()` is an iterator over the
messages published from the moment it starts. Beaver polls the file for all
channels of a database in one background loop, so a hundred listeners cost
one query per poll, not a hundred.

```{python continue}
alerts = db.channel("alerts")


def form():
    with BeaverDB("helpdesk.db") as other:
        time.sleep(0.2)
        other.channel("alerts").publish({"id": "T-1102", "subject": "Brakes failed"})
        other.channel("alerts").publish({"id": "T-1103", "subject": "Crash, wheel bent"})


threading.Thread(target=form).start()

received = []
for message in alerts.listen():
    print(message.payload["id"], "on", message.channel)
    received.append(message)
    if len(received) == 2:
        break
```

Each item is a `ChannelMessage` with the `channel`, the `payload` and the
`timestamp` it was published at. Published messages are also kept, so an
agent who signs in late can read what they missed with `history(limit=...)`.
`count()` and `clear()` manage that history.

```{python continue}
print([m.payload["id"] for m in alerts.history(limit=10)], alerts.count())
```

## Callbacks

Listening in a loop suits a program whose job is to listen. Most code wants
the opposite: run a function when something happens, and carry on.
`db.events(name)` is an event bus on top of a channel. `attach(event,
callback)` registers a function, and `emit(event, payload)` calls every
function attached to that event, in every program with the file open.

```{python continue}
bus = db.events("desk")
calls = []


def on_closed(event):
    calls.append(event.payload["ticket"])


bus.attach("ticket_closed", on_closed)
bus.emit("ticket_closed", {"ticket": "T-1101"})
time.sleep(0.3)
print(calls)
```

The callback receives an `Event` with its `event` name, `payload`, `id` and
`timestamp`. It runs on beaver's background thread, so keep it short, or have
it hand the work to a queue. An `async def` callback is scheduled as a task
instead. `detach(event, callback)` removes it.

```{python continue}
bus.detach("ticket_closed", on_closed)
bus.emit("ticket_closed", {"ticket": "T-1102"})
time.sleep(0.3)
print(calls)
```

`attach` also returns an `EventHandler` whose `off()` would remove the
callback, but from `BeaverDB` that `off()` is a coroutine that never runs
(issue #48). Use `detach`.

## Changes to a collection

Every collection has a bus of its own, and its writing methods emit on it: a
dictionary emits `set` and `del`, a list `push`, and so on. `on(event,
callback)` attaches to it, which turns "tell me when a ticket gets an owner"
into one line.

```{python continue}
owners = db.dict("owners")
changes = []
owners.on("set", lambda event: changes.append(event.payload["key"]))

owners["T-1101"] = "ana"
owners["T-1102"] = "luis"
time.sleep(0.3)
print(changes)
db.close()
```

The bus of a collection only starts once something is attached to it, so a
collection nobody listens to emits nothing and costs nothing.

## The program

Alerts for the desk: the form publishes urgent tickets, and each agent's
screen shows the ones it missed and then the new ones as they come.

```{python export=examples/alerts.py}
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
```

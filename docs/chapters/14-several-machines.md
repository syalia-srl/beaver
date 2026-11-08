# Several machines

```{python echo=false output=false}
import glob, os

for f in glob.glob("helpdesk.db*"):
    os.remove(f)
```

The desk outgrows one machine. The web page runs on one server, and the
mailbox reader moves to another. Both need the ticket queue and the
settings. An SQLite file is opened by processes on the machine that has it:
SQLite's locking is not reliable over a network filesystem, so putting
`helpdesk.db` on a shared drive and opening it from both servers invites a
corrupted file. Until now, everything that touched the desk ran where the
file is.

## A server for the file

`beaver serve` runs an HTTP server on top of a database file. It needs the
`remote` extra. `--api-key` (or the `BEAVER_API_KEY` variable) makes every
request carry that key as a bearer token.

```bash
beaver serve --db helpdesk.db --host 0.0.0.0 --port 8000 --api-key "$BEAVER_API_KEY"
```

This chapter starts it the same way, as a background process on a free port:

```{python continue}
import atexit
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

sock = socket.socket()
sock.bind(("127.0.0.1", 0))
port = sock.getsockname()[1]
sock.close()

beaver_cli = Path(sys.executable).parent / "beaver"
server = subprocess.Popen(
    [str(beaver_cli), "serve", "--db", "helpdesk.db", "--port", str(port), "--api-key", "desk-key"],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
atexit.register(server.terminate)  # stop it when this program ends
URL = f"http://127.0.0.1:{port}"
for _ in range(100):
    try:
        httpx.get(f"{URL}/docs")
        break
    except httpx.ConnectError:
        time.sleep(0.1)
print("without the key:", httpx.get(f"{URL}/docs").status_code)
print("with it:", httpx.get(f"{URL}/docs", headers={"Authorization": "Bearer desk-key"}).status_code)
```

The server is a FastAPI app. `/docs` is its interactive API page, which lists
every route, and like every route it needs the key.

## The client

`beaver.connect(url, api_key=...)` returns a `BeaverClient`, which has the
same methods as `BeaverDB` for the collections the server exposes:
dictionaries, lists, queues and logs. The mailbox reader on the other machine
changes one line.

```{python continue}
from beaver import connect

desk = connect(URL, api_key="desk-key")
print(type(desk).__name__)

desk.dict("settings")["shop"] = "Spoke & Chain"
desk.queue("tickets").put({"id": "T-1701", "subject": "Brakes"}, priority=1)
desk.log("audit").log({"agent": "mailbox", "action": "import", "ticket": "T-1701"})

print(desk.dict("settings")["shop"], len(desk.dict("settings")), "shop" in desk.dict("settings"))
```

Behind it, `BeaverClient` runs an `AsyncBeaverClient` on a background thread,
as `BeaverDB` runs `AsyncBeaverDB`. `connect(url, sync=False)` returns the
`AsyncBeaverClient` itself for async code. Its collections are `RemoteDict`,
`RemoteList`, `RemoteQueue` and `RemoteLog`, which send each call as an HTTP
request.

What the server wrote is in the file, where local code reads it as before:

```{python continue}
from beaver import BeaverDB

with BeaverDB("helpdesk.db") as local:
    print(local.queue("tickets").peek().data, local.log("audit").count())
```

## What does not cross the wire

Some methods cannot work over plain requests: iterating over a dictionary's
keys (a stream), `live()` on a log (an endless one), `batched()`, `dump()` and
`load()`. The remote collections raise `LocalOnlyError` for them, with the
reason:

```{python continue}
from beaver import LocalOnlyError

for attempt in (lambda: list(desk.dict("settings").keys()), lambda: next(iter(desk.log("audit").live()))):
    try:
        attempt()
    except LocalOnlyError as e:
        print("LocalOnlyError:", e)
```

Documents, vectors, graphs, blobs, locks, channels, sketches and events are
not served in 2.4: the client has no `docs()`, `lock()` and so on. A program
that needs them runs where the file is, and the other machines reach it
through the queue and the dictionaries, or through an API of your own.

Some results also come back in another shape than locally. In 2.4, a remote
queue's `get()` returns a plain dictionary rather than a `QueueItem`, and a
remote log's `range()` a list of dictionaries rather than `LogEntry` tuples
(issue #50):

```{python continue}
print(desk.queue("tickets").get(timeout=1))
print(desk.log("audit").range())
```

## Errors over the wire

An exception on the server is sent back as an `ErrorEnvelope`, a small JSON
object with the exception's class name and message, and raised again in the
client. `KeyError`, `ValueError`, `TimeoutError`, pydantic's
`ValidationError`, `TransactionTimeoutError` and the schema errors of chapter
16 come back as themselves, so the same `except` clauses work locally and
remotely. Any other exception arrives as `BeaverRemoteError`, and so does a
missing or wrong API key, which the server's `BearerAuthMiddleware` rejects
before any collection is touched. In 2.4 a remote `KeyError` carries its
message quoted twice (issue #50).

```{python continue}
from beaver import BeaverRemoteError

try:
    desk.dict("settings")["holiday"]
except KeyError as e:
    print("KeyError:", e)

try:
    connect(URL, api_key="a guess").dict("settings")["shop"]
except BeaverRemoteError as e:
    print("BeaverRemoteError:", e)

desk.close()
server.terminate()
server.wait()
```

## The program

The mailbox reader, now on its own machine. It reads the server's address
and key from the environment, and falls back to the local file when there is
no server, so the same program runs in both places.

```{python export=examples/remote_reader.py}
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
```

# Signing agents in

```{python echo=false output=false}
import glob, os

for f in glob.glob("helpdesk.db*"):
    os.remove(f)
```

The desk has three agents now, and each one signs in before answering tickets.
With what chapter 1 taught, an agent is a dictionary value: a name, a role and
a password.

```{python continue}
from beaver import BeaverDB

db = BeaverDB("helpdesk.db")
agents = db.dict("agents")
agents["ana"] = {"name": "Ana", "role": "lead", "password": "correct-horse"}
agents["luis"] = {"name": "Luis", "role": "agent", "password": "battery-staple"}


def sign_in(login, password):
    agent = agents.fetch(login)
    return agent is not None and agent["password"] == password


print(sign_in("ana", "correct-horse"), sign_in("ana", "guess"))
```

Two things are wrong with it. The passwords sit in the file as plain text,
and the file is a standard SQLite database that anyone with a copy can read:

```{python continue}
import sqlite3

row = sqlite3.connect("helpdesk.db").execute(
    "SELECT value FROM __beaver_dicts__ WHERE dict_name = 'agents' AND key = 'ana'"
).fetchone()
print(row[0])
```

And nothing says what an agent is. A typo such as `"rol"` goes in silently,
and every reader has to remember the keys.

## Typed records

Give `db.dict()` a pydantic model, and every read comes back as an instance of
it. Writes take an instance too.

```{python continue}
from pydantic import BaseModel


class Agent(BaseModel):
    name: str
    role: str


staff = db.dict("staff", model=Agent)
staff["ana"] = Agent(name="Ana", role="lead")
ana = staff["ana"]
print(repr(ana), ana.role)
```

The model is applied when a value is read, not when it is written. A plain
dictionary with a wrong field type is stored as it is, and the error shows up
at the first read:

```{python continue}
staff["ghost"] = {"name": "Ghost", "role": 42}
try:
    staff["ghost"]
except Exception as e:
    print(type(e).__name__, str(e).splitlines()[0])
del staff["ghost"]
```

So write model instances, and pydantic checks them when you build them.

## Passwords you never store

A sign-in check never needs the password back, only to know whether the one
typed matches. `Secret` holds a salted PBKDF2 hash of a string. Comparing it
with `==` to a string hashes that string with the same salt and compares the
results. It needs the `security` extra.

```{python continue}
from beaver import Secret


class Agent(BaseModel):
    name: str
    role: str
    password: Secret


accounts = db.dict("accounts", model=Agent)
accounts["ana"] = Agent(name="Ana", role="lead", password=Secret("correct-horse"))

stored = accounts["ana"].password
print(stored == "correct-horse", stored == "guess")
print(stored.model_dump().keys())
```

The new model goes into a new dictionary, `accounts`. Within one `BeaverDB`,
`db.dict(name)` returns the same object for the same name, with the model of
its first call, so reusing `staff` would keep reading the old `Agent`.

The file holds only `hash` and `salt`. A `Secret` goes inside a model, as
here. Put into a plain dictionary value, it cannot be stored: in beaver 2.4
the write fails with a `TypeError` (issue #43).

```{python continue}
try:
    agents["ana"] = {"name": "Ana", "password": Secret("correct-horse")}
except TypeError as e:
    print("TypeError:", e)
```

## Values you need back, encrypted

Some values the desk must read back: the API key of the courier service it
books returns with. Hashing does not help there. Pass `secret=` to
`db.dict()`, and every value of that dictionary is encrypted with a key
derived from it (Fernet, from the `cryptography` package) before it reaches
the file.

```{python continue}
keys = db.dict("integrations", secret="shop master key")
keys["courier"] = {"api_key": "ck_live_51H8"}
print(keys["courier"])

row = sqlite3.connect("helpdesk.db").execute(
    "SELECT value FROM __beaver_dicts__ WHERE dict_name = 'integrations'"
).fetchone()
print(row[0][:40], "...")
db.close()
```

The next program that opens the file needs the same secret. A wrong one is
refused when the dictionary is first used:

```{python continue}
with BeaverDB("helpdesk.db") as db:
    try:
        db.dict("integrations", secret="a guess")["courier"]
    except ValueError as e:
        print("ValueError:", e)

with BeaverDB("helpdesk.db") as db:
    print(db.dict("integrations", secret="shop master key")["courier"])
```

Opened with no secret at all, the read fails too, but today with a
`JSONDecodeError` rather than a message that says the dictionary is encrypted
(issue #45). For the same reason as with models, the secret of the first
`db.dict(name)` call in a `BeaverDB` is the one that counts.

## Sessions that expire

After signing in, an agent gets a session token that should stop working
after a while. `set` takes `ttl_seconds`: once it passes, the key reads as
missing and is deleted on that read.

```{python continue}
import secrets
import time

db = BeaverDB("helpdesk.db")
sessions = db.dict("sessions")

token = secrets.token_hex(8)
sessions.set(token, "ana", ttl_seconds=0.5)
print(sessions.fetch(token))
time.sleep(0.6)
print(sessions.fetch(token), token in sessions)
db.close()
```

## The program

Sign-in for the desk: agents with hashed passwords, and sessions that last
eight hours.

```{python export=examples/sign_in.py}
import secrets

from pydantic import BaseModel

from beaver import BeaverDB, Secret

SESSION_SECONDS = 8 * 3600


class Agent(BaseModel):
    name: str
    role: str
    password: Secret


def add_agent(db: BeaverDB, login: str, name: str, role: str, password: str):
    db.dict("accounts", model=Agent)[login] = Agent(
        name=name, role=role, password=Secret(password)
    )


def sign_in(db: BeaverDB, login: str, password: str) -> str | None:
    agent = db.dict("accounts", model=Agent).fetch(login)
    if agent is None or agent.password != password:
        return None
    token = secrets.token_hex(16)
    db.dict("sessions").set(token, login, ttl_seconds=SESSION_SECONDS)
    return token


def who(db: BeaverDB, token: str) -> str | None:
    return db.dict("sessions").fetch(token)


def main():
    with BeaverDB("helpdesk.db") as db:
        add_agent(db, "luis", "Luis", "agent", "battery-staple")
        print("wrong password:", sign_in(db, "luis", "guess"))
        token = sign_in(db, "luis", "battery-staple")
        print("signed in as:", who(db, token))


if __name__ == "__main__":
    main()
```

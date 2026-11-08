# Testing without a database

```{python echo=false output=false}
import glob, os

for f in glob.glob("helpdesk.db*") + glob.glob("test-*.db*"):
    os.remove(f)
```

The sign-in code of chapter 2 takes a `BeaverDB` and opens its collections by
name. Its tests then need a database file, a fresh one per test, and every
test that runs it starts beaver's background thread and writes to disk. The
function only needs one thing from the database: a dictionary of accounts.

```{python continue}
from pydantic import BaseModel

from beaver import BeaverDB, Secret


class Agent(BaseModel):
    name: str
    role: str
    password: Secret


def can_sign_in(db: BeaverDB, login: str, password: str) -> bool:
    agent = db.dict("accounts", model=Agent).fetch(login)
    return agent is not None and agent.password == password


with BeaverDB("test-1.db") as db:
    db.dict("accounts", model=Agent)["ana"] = Agent(name="Ana", role="lead", password=Secret("pw"))
    print(can_sign_in(db, "ana", "pw"), can_sign_in(db, "ana", "nope"))
```

Taking the whole database also hides what the function uses, and ties it to
the local engine: the `BeaverClient` of chapter 14 is not a `BeaverDB`.

## The protocols

`beaver.interfaces` describes every collection as a `typing.Protocol`: the
methods it has and their types, with no implementation. Code annotated with
a protocol accepts anything that has those methods, which a type checker
such as mypy verifies.

For each collection there is a sync protocol and an async one: `IBeaverDict`
and `IAsyncBeaverDict`, `IBeaverList` and `IAsyncBeaverList`, `IBeaverQueue`
and `IAsyncBeaverQueue`, `IBeaverLog` and `IAsyncBeaverLog`, `IBeaverDocuments`
and `IAsyncBeaverDocuments`, `IBeaverVectors` and `IAsyncBeaverVectors`,
`IBeaverGraph` and `IAsyncBeaverGraph`, `IBeaverBlob` and `IAsyncBeaverBlob`,
`IBeaverChannel` and `IAsyncBeaverChannel`, `IBeaverLock` and
`IAsyncBeaverLock`, `IBeaverSketch` and `IAsyncBeaverSketch`, `IBeaverEvents`
and `IAsyncBeaverEvents`. The databases are `IBeaverDB` and `IAsyncBeaverDB`.
The batches are `IDictBatch`, `IListBatch`, `ILogBatch`, `IBlobBatch`,
`IDocumentsBatch` and `ISketchBatch`, the document query builder is
`IDocumentQuery`, and an event subscription is an `IEventHandler`. The
`BeaverDB` methods are annotated with them: `db.dict()` is declared to return
an `IBeaverDict`.

So the function asks for a dictionary of agents, and the caller decides which:

```{python continue}
from beaver.interfaces import IBeaverDict


def can_sign_in(accounts: IBeaverDict[Agent], login: str, password: str) -> bool:
    agent = accounts.fetch(login)
    return agent is not None and agent.password == password


with BeaverDB("test-2.db") as db:
    accounts = db.dict("accounts", model=Agent)
    accounts["ana"] = Agent(name="Ana", role="lead", password=Secret("pw"))
    print(can_sign_in(accounts, "ana", "pw"))
```

## A fake for tests

In a test, the dictionary can be a small class that keeps its items in
memory. It has to have every method of `IBeaverDict` for the type checker to
accept it, but most of them are one line.

```{python continue}
import json
from typing import IO, Any, Iterator


class MemoryDict[T]:
    def __init__(self) -> None:
        self._items: dict[str, T] = {}

    def get(self, key: str) -> T:
        return self._items[key]

    def set(self, key: str, value: T, ttl_seconds: float | None = None) -> None:
        self._items[key] = value

    def delete(self, key: str) -> None:
        del self._items[key]

    def fetch(self, key: str, default: Any = None) -> T | Any:
        return self._items.get(key, default)

    def pop(self, key: str, default: Any = None) -> T | Any:
        return self._items.pop(key, default)

    def keys(self) -> Iterator[str]:
        return iter(list(self._items))

    def values(self) -> Iterator[T]:
        return iter(list(self._items.values()))

    def items(self) -> Iterator[tuple[str, T]]:
        return iter(list(self._items.items()))

    def clear(self) -> None:
        self._items.clear()

    def count(self) -> int:
        return len(self._items)

    def dump(self, fp: IO[str] | None = None) -> dict | None:
        return {"items": list(self._items)}

    def load(self, fp: IO[str], format: str = "json", strategy: str = "overwrite") -> None:
        raise NotImplementedError

    __getitem__ = get
    __setitem__ = set
    __delitem__ = delete
    __len__ = count

    def __contains__(self, key: str) -> bool:
        return key in self._items

    def __iter__(self) -> Iterator[str]:
        return self.keys()


fake: MemoryDict[Agent] = MemoryDict()
fake["ana"] = Agent(name="Ana", role="lead", password=Secret("pw"))
print(can_sign_in(fake, "ana", "pw"), can_sign_in(fake, "luis", "pw"))
```

No file and no thread: the test runs in microseconds, and checks the sign-in
rule rather than beaver. Beaver itself has its own tests.

## Only for the type checker

The protocols are checked statically. `isinstance` with them works on the
async collections, which are ordinary objects, but not on what `BeaverDB`
returns: those are `BeaverBridge` proxies that forward each method to the
async engine on demand, and `isinstance` only sees the methods a class
declares.

```{python continue}
from beaver import AsyncBeaverDB
from beaver.interfaces import IAsyncBeaverDict

with BeaverDB("test-3.db") as db:
    print("sync:", isinstance(db.dict("accounts"), IBeaverDict), type(db.dict("accounts")).__name__)
print("async:", isinstance(AsyncBeaverDB("test-3.db").dict("accounts"), IAsyncBeaverDict))
```

So write `accounts: IBeaverDict[Agent]` in signatures and run mypy, and do
not branch on `isinstance` at runtime.

## The program

The sign-in rule, its test against the fake, and the same rule on a real
collection:

```{python export=examples/typed_sign_in.py}
from typing import IO, Any, Iterator

from pydantic import BaseModel

from beaver import BeaverDB, Secret
from beaver.interfaces import IBeaverDict


class Agent(BaseModel):
    name: str
    role: str
    password: Secret


def can_sign_in(accounts: IBeaverDict[Agent], login: str, password: str) -> bool:
    agent = accounts.fetch(login)
    return agent is not None and agent.password == password


class MemoryDict[T]:
    """Every method of IBeaverDict, kept in memory, for tests."""

    def __init__(self) -> None:
        self._items: dict[str, T] = {}

    def get(self, key: str) -> T:
        return self._items[key]

    def set(self, key: str, value: T, ttl_seconds: float | None = None) -> None:
        self._items[key] = value

    def delete(self, key: str) -> None:
        del self._items[key]

    def fetch(self, key: str, default: Any = None) -> T | Any:
        return self._items.get(key, default)

    def pop(self, key: str, default: Any = None) -> T | Any:
        return self._items.pop(key, default)

    def keys(self) -> Iterator[str]:
        return iter(list(self._items))

    def values(self) -> Iterator[T]:
        return iter(list(self._items.values()))

    def items(self) -> Iterator[tuple[str, T]]:
        return iter(list(self._items.items()))

    def clear(self) -> None:
        self._items.clear()

    def count(self) -> int:
        return len(self._items)

    def dump(self, fp: IO[str] | None = None) -> dict | None:
        return {"items": list(self._items)}

    def load(
        self, fp: IO[str], format: str = "json", strategy: str = "overwrite"
    ) -> None:
        raise NotImplementedError

    __getitem__ = get
    __setitem__ = set
    __delitem__ = delete
    __len__ = count

    def __contains__(self, key: str) -> bool:
        return key in self._items

    def __iter__(self) -> Iterator[str]:
        return self.keys()


def test_sign_in() -> None:
    accounts: MemoryDict[Agent] = MemoryDict()
    accounts["ana"] = Agent(name="Ana", role="lead", password=Secret("pw"))
    assert can_sign_in(accounts, "ana", "pw")
    assert not can_sign_in(accounts, "ana", "guess")
    assert not can_sign_in(accounts, "luis", "pw")


def main() -> None:
    test_sign_in()
    print("test_sign_in passed")
    with BeaverDB("helpdesk.db") as db:
        accounts = db.dict("accounts", model=Agent)
        accounts["ana"] = Agent(name="Ana", role="lead", password=Secret("pw"))
        print("on the real collection:", can_sign_in(accounts, "ana", "pw"))


if __name__ == "__main__":
    main()
```

mypy accepts both callers, the fake and the real collection. To see that the
check means something, the block also runs it on a copy of the program whose
fake lacks `count` and `__len__`:

```{python}
import subprocess
import sys
from pathlib import Path


def mypy(path):
    result = subprocess.run(
        [sys.executable, "-m", "mypy", "--no-error-summary", "--ignore-missing-imports", path],
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout.strip().splitlines()[:2]


program = Path("examples/typed_sign_in.py").read_text()
broken = program.replace("    def count(self) -> int:\n        return len(self._items)\n", "")
Path("broken_sign_in.py").write_text(broken.replace("__len__ = count", ""))

print(mypy("examples/typed_sign_in.py"))
print(mypy("broken_sign_in.py"))
Path("broken_sign_in.py").unlink()
```

This works because beaver ships a `py.typed` marker, which tells type
checkers to read its annotations. Version 2.4.2 and earlier lack it (issue
#51), and there mypy treats every beaver type as `Any` and accepts the broken
fake too.

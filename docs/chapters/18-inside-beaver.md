# Inside beaver

```{python echo=false output=false}
import glob, os

for f in glob.glob("inside.db*"):
    os.remove(f)
```

This chapter is for people who change beaver rather than use it: how the
pieces of the earlier chapters are built, and where to look in the source.
Every block runs against the package like the rest of the guide, and some of
them reach into private attributes to show what is there. Code that uses
beaver should not.

## One file, a fixed set of tables

Every collection of every kind lives in a small, fixed set of tables, created
with `CREATE TABLE IF NOT EXISTS` each time a database is opened. A new kind
of data adds a table, and an old file simply gains it on its next open: there
is no migration step for additive changes. Every table name is dunder-quoted,
which is how 2.x tells its files from 1.x ones (chapter 16).

```{python continue}
import sqlite3

from beaver import BeaverDB

with BeaverDB("inside.db") as db:
    db.dict("settings")["shop"] = "Spoke & Chain"

conn = sqlite3.connect("inside.db")
tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '__beaver%' ORDER BY name")]
print(len(tables), "tables:", ", ".join(tables))
print("user_version:", conn.execute("PRAGMA user_version").fetchone()[0])
print(conn.execute("SELECT dict_name, key, value FROM __beaver_dicts__").fetchall())
conn.close()
```

`user_version` is the schema version, `BEAVER_DB_VERSION` in `core.py`. A
file whose version is higher than the running beaver's fails to open with
`BeaverIncompatibleSchemaError`, so raising it is a deliberate break of file
compatibility. Prefer a change that fits as a new table.

## An async engine and a sync portal

`AsyncBeaverDB` owns one `aiosqlite` connection in WAL mode, and every
collection of that database shares it. `BeaverDB` starts a thread running an
event loop, builds the `AsyncBeaverDB` on it, and hands each collection back
wrapped in a `BeaverBridge`. The bridge forwards every attribute access to
the async object: a coroutine is run on the loop and its result returned, an
async generator becomes a sync iterator, and an async context manager is
wrapped so that `with` works. `len()`, `[]`, `in` and iteration map to
`count`, `get` and `set`, `contains` and `__aiter__`.

```{python continue}
import threading

db = BeaverDB("inside.db")
settings = db.dict("settings")
print(type(settings).__name__, "->", type(settings._async_obj).__name__)
print([t.name for t in threading.enumerate() if t.name.startswith("BeaverDB")])
```

So the logic is written once, in the async classes, and the sync interface
follows. A new method on a manager needs nothing in the bridge.

Every factory method returns the same object for the same name, from a cache
on the engine (`singleton()`). That is why the model and the secret of the
first call win (chapter 2), and why locks and listeners are shared within a
database.

```{python continue}
print(db.dict("settings")._async_obj is db.dict("settings")._async_obj)
db.close()
```

## Managers

Each collection class derives from `AsyncBeaverBase`. The base keeps the name,
the optional model, and serialization: a pydantic model is dumped with
`model_dump_json`, anything else with `json.dumps`, and reads validate with
the model when there is one. It also gives every collection two locks of the
kind chapter 5 described: a public one, which `with collection:` takes, and an
internal one with a five-second TTL, held for milliseconds around each write.

Three decorators in `manager.py` carry the concurrency rules. `@atomic` takes
the internal lock and a transaction, for writes. `@read_atomic` takes only a
transaction, so a read never sees another task's uncommitted write on the
shared connection, and never writes a lock row. `@emits` publishes an event
after a write, but only once something has attached to the collection's bus
(chapter 11), so collections nobody listens to pay nothing.

`AsyncBeaverDict` adds encryption on top of the base serialization: with a
secret, values pass through a `Cipher`, which derives a Fernet key from the
secret with PBKDF2 and a per-dictionary salt, and whose `encrypt` and
`decrypt` work on bytes. The salt and a known encrypted value, to verify the
secret, are kept in the internal `__security__` dictionary, which `is_system`
marks as never encrypted.

```{python continue}
from beaver.security import Cipher

cipher = Cipher("shop master key")
token = cipher.encrypt(b"ck_live_51H8")
print(len(cipher.salt), "byte salt;", Cipher("shop master key", salt=cipher.salt).decrypt(token))
```

## Transactions on one connection

All writers of a process share one connection, so a transaction is an
`asyncio.Lock` held by one task: `Transaction` takes it, issues `BEGIN
IMMEDIATE`, and commits at the end of the outermost block of that task.
Inner blocks of the same task pass through, which is what lets `@atomic`
methods run inside a caller's transaction. SQLite's busy timeout only
arbitrates between connections, so the wait for that lock has its own bound,
`connection_timeout`, and `TransactionTimeoutError` when it runs out. If the
task that held it finished without releasing it, the next writer sees the
owner is done, rolls its transaction back, logs a warning on the `beaver`
logger and proceeds.

One consequence for operations: in WAL mode, readers keep working while
writers queue. A process stuck holding the write lock still answers reads, so
a health check of a beaver-backed service has to write to mean anything.

## Lists without renumbering

A list's order is a text key per item, not an index. Inserting between two
items asks `key_between(a, b)` for a key that sorts between theirs, so an
insert writes one row and moves none.

```{python continue}
from beaver._fracdex import key_between

first = key_between(None, None)
last = key_between(first, None)
middle = key_between(first, last)
print(first, middle, last, sorted([last, first, middle]) == [first, middle, last])
```

## Channels and events

All channels of a database share one `PubSubEngine`: a single task that polls
the `__beaver_pubsub_log__` table for rows newer than the last it saw, and
pushes each one onto the `asyncio.Queue` of every listener of that channel.
`listen()` registers a queue, and leaving the iterator unregisters it
(`unsubscribe`). An events bus is a channel named after it, plus a dispatch
task that reads the channel and calls the attached callbacks. `close()` stops
both kinds of task.

## Search

`docs.index()` stores the document as JSON and flattens every string field,
nested ones included, into the `__beaver_fts_index__` FTS5 table, one row per
field path, which is what lets `search(on=[...])` restrict to fields. With
`fuzzy=True` it also writes the trigrams of each field to
`__beaver_trigrams__`. A fuzzy search counts the query's trigrams that each
document shares, and returns the highest counts. `where=` filters compile to
`json_extract` predicates over the document JSON.

Field indexes (chapter 13) live in `indexing.py`. `extract_path` walks a
dotted path through models and dictionaries, `normalize` turns a scalar into
its text form and, for a number, a numeric form, so that range filters
compare numbers as numbers and the string `"10"` stays a string, and
`build_rows` produces an item's index rows. At query time, `plan_filters`
splits the filters into those an index can answer, through
`compile_indexed_filter`, and those it cannot, through
`compile_scan_filters`. A field's index is trusted only once it is marked
complete, so a half-built index makes queries slower, never wrong.

```{python continue}
from beaver import q
from beaver.indexing import extract_path, normalize

print(extract_path({"agent": {"name": "ana"}}, "agent.name"), normalize("10"), normalize(10))
print(q().agent.name == "ana")
```

The second line is what a `q` expression builds: a `Query` collects the dotted
path through attribute access, and a comparison returns a `Filter` with the
path, the operator and the value.

## Vectors

Vectors are stored as raw float32 bytes and searched with numpy over the
whole matrix. Past 10,000 vectors, each vector is also hashed with 16 random
hyperplanes into a bucket of `__beaver_lsh_index__`, and a search scores only
the query's bucket and its 16 one-bit neighbours (chapter 7). Everything is
pure numpy: a compiled ANN library would break the rule that beaver installs
anywhere Python does.

## Sketches

An `ApproximateSet` packs a HyperLogLog and a Bloom filter into one byte
array, sized from the capacity and error rate, and `to_bytes()` is what is
stored. Each `add` reloads the bytes, sets the bits and saves them inside a
transaction. `contains` reads the copy in memory (chapter 12).

```{python continue}
from beaver.sketches import ApproximateSet

s = ApproximateSet(capacity=1000, error_rate=0.01)
for n in range(100):
    s.add(f"id-{n}".encode())
print(b"id-7" in s, b"id-x" in s, len(s), len(s.to_bytes()), "bytes")
```

## One decorator, three ways in

A manager method marked `@expose(path=..., method=..., cli_name=...,
cli_help=...)` is reachable from the command line, the HTTP server and the
remote client at once. The decorator only attaches an `EndpointMeta` to the
function. `build_typer_for` walks a manager class for those and registers a
CLI command per method, `create_app` mounts an HTTP route per method on a
FastAPI app, and the client builds a dispatcher per method from the same
metadata. `@local_only("reason")` marks what cannot cross the wire, and the
remote classes raise `LocalOnlyError` with that reason. A method with neither
decorator is local by accident rather than by decision.

```{python continue}
from beaver.dicts import AsyncBeaverDict

print(AsyncBeaverDict.set.__beaver_endpoint__)
print(AsyncBeaverDict.keys.__beaver_local_only__)
```

The CLI uses those commands directly, on a file or on a server (`--url`):

```{python continue}
import subprocess
import sys
from pathlib import Path

beaver_cli = str(Path(sys.executable).parent / "beaver")
print(subprocess.run([beaver_cli, "--db", "inside.db", "--raw", "dict", "settings", "get", "shop"], capture_output=True, text=True).stdout)
```

On the server side, an exception becomes an `ErrorEnvelope` with
`envelope_from_exception`, and `http_code_for` picks its status code (404 for
`KeyError`, 409 for a timeout, 422 for validation, 400 for `ValueError`, 500
otherwise). The client turns the envelope back into the exception with
`raise_from_envelope`, or into `BeaverRemoteError` when the class is not one
it knows. `BearerAuthMiddleware` checks the API key before any route runs.

```{python continue}
from beaver.errors import envelope_from_exception, http_code_for

error = KeyError("T-404")
print(envelope_from_exception(error), http_code_for(error))
```

## The cache that is not wired in

`cache.py` holds a per-manager read cache: the `ICache` protocol, a
`LocalCache` that invalidates itself when a version counter in the file
changes (`touch` bumps it), `CacheStats` with `hit_rate`,
`invalidation_rate` and `operations` from its `stats`, and the `@cached` and
`@invalidates_cache` decorators. None of it is in use in 2.4.
`AsyncBeaverDB.cache()` always returns the `DummyCache`, whose `get` misses
and whose `invalidate` does nothing, and no manager method is decorated. The
`cache_timeout` argument of `AsyncBeaverDB` is accepted and ignored.

```{python continue}
from beaver import AsyncBeaverDB

cache = AsyncBeaverDB("inside.db").cache("dict:settings")
print(type(cache).__name__, cache.get("shop"), cache.stats())
```

## Migration internals

`beaver.migrate` opens the 1.x source read-only, so that not even a WAL
checkpoint touches it, and refuses a destination that exists. Tables whose
schema did not change are copied as they are. Lists get new fractional keys
in their old order, and the full-text and trigram indexes are rebuilt from
the documents. `total_rows` on a `MigrationReport` adds up the rows it reports.

## Working on beaver

```bash
make sync           # uv sync with the security and remote extras
uv run black .      # format; CI runs black --check
make test-unit      # the default target, about half a minute
make test-all       # every suite, including concurrency
make docs-check     # this guide: render, tangle, run the examples, rift
```

`pytest.ini` sets `asyncio_mode = auto` and a 30-second timeout per test, so
a test that deadlocks on a lock fails instead of hanging the run. Dependencies
stay few on purpose: `aiosqlite`, `numpy`, `pydantic`, `rich` and `typer` in
the core, the HTTP stack and `cryptography` behind extras.

When you add a public class or method, name it in the chapter where a reader
first needs it. `rift check` fails the docs gate on a public class that no
chapter names.

## The program

A small inspector for any beaver file: its tables with their row counts, and
its schema version.

```{python export=examples/inspect_file.py}
import sqlite3
import sys


def inspect(path: str) -> list[str]:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        lines = [f"{path}: schema version {version}"]
        names = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
            " AND name LIKE '__beaver%' ORDER BY name"
        ).fetchall()
        for (name,) in names:
            rows = conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            if rows:
                lines.append(f"  {name:<32} {rows} rows")
        return lines
    finally:
        conn.close()


def main():
    if len(sys.argv) > 1:
        path = sys.argv[1]
    else:
        from beaver import BeaverDB

        path = "inspect-demo.db"
        with BeaverDB(path) as db:
            db.dict("settings")["shop"] = "Spoke & Chain"
    print("\n".join(inspect(path)))


if __name__ == "__main__":
    main()
```

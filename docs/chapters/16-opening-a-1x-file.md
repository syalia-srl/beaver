# Opening a 1.x file

```{python echo=false output=false}
import glob, os

for f in glob.glob("old-desk*.db*") + glob.glob("future.db*"):
    os.remove(f)
```

Before this desk, the shop ran a small script on beaver 1.3, and its file
still has the old settings and threads. Beaver 1.x named its tables
`beaver_dicts`, `beaver_lists` and so on; 2.x names them `__beaver_dicts__`,
`__beaver_lists__`. Here is a small file in the 1.x layout, built by hand with
`sqlite3` the way 1.x wrote it:

```{python continue}
import json
import sqlite3

old = sqlite3.connect("old-desk.db")
old.execute(
    "CREATE TABLE beaver_dicts (dict_name TEXT NOT NULL, key TEXT NOT NULL,"
    " value TEXT NOT NULL, expires_at REAL, PRIMARY KEY (dict_name, key))"
)
old.execute(
    "CREATE TABLE beaver_lists (list_name TEXT NOT NULL, item_order REAL NOT NULL,"
    " item_value TEXT NOT NULL, PRIMARY KEY (list_name, item_order))"
)
old.executemany(
    "INSERT INTO beaver_dicts VALUES (?, ?, ?, NULL)",
    [
        ("__metadata__", "version", json.dumps("1.3.0")),
        ("settings", "shop", json.dumps("Spoke & Chain")),
        ("settings", "hours", json.dumps({"open": 9, "close": 18})),
    ],
)
old.executemany(
    "INSERT INTO beaver_lists VALUES (?, ?, ?)",
    [("thread:T-0042", 1.0, json.dumps("My bell is broken")), ("thread:T-0042", 2.0, json.dumps("Fixed in store"))],
)
old.commit()
old.close()
```

## Beaver refuses it

A 2.x reader that ignored the old tables would see an empty database, and
the first write would start a new dataset beside the old one, with nothing
failing. So 2.x refuses to open a 1.x file, with
`BeaverLegacySchemaError`:

```{python continue}
from beaver import BeaverDB, BeaverLegacySchemaError

try:
    BeaverDB("old-desk.db")
except BeaverLegacySchemaError as e:
    print(str(e).splitlines()[0])
    print(str(e).splitlines()[1])
```

The same holds for a file newer than the running beaver. Beaver records its
schema version in SQLite's `user_version`, and a file written by a later,
incompatible release fails with `BeaverIncompatibleSchemaError`, of which the
legacy error is a kind:

```{python continue}
from beaver import BeaverIncompatibleSchemaError

future = sqlite3.connect("future.db")
future.execute("PRAGMA user_version = 99")
future.close()
try:
    BeaverDB("future.db")
except BeaverIncompatibleSchemaError as e:
    print(type(e).__name__, "|", str(e).splitlines()[0])
```

## Migrating

`beaver migrate` copies a 1.x file into a new 2.x file. It opens the source
read-only, and never writes to it, so a failed migration leaves the original
as it was. `--dry-run` reports what it would copy and writes nothing:

```{python continue}
import subprocess
import sys
from pathlib import Path

beaver_cli = str(Path(sys.executable).parent / "beaver")
print(subprocess.run([beaver_cli, "migrate", "old-desk.db", "--dry-run"], capture_output=True, text=True).stdout)
```

Without it, the copy goes to `old-desk.db.migrated`, or to `--output`. List
positions are renumbered, because 2.x keeps them as fractional keys:

```{python continue}
run = subprocess.run([beaver_cli, "migrate", "old-desk.db", "-o", "old-desk-2x.db"], capture_output=True, text=True)
print(run.stdout)

with BeaverDB("old-desk-2x.db") as db:
    print(db.dict("settings")["hours"], list(db.list("thread:T-0042")))
```

Adopting the copy is then two renames, which the command prints. If a 1.x file
was already opened by an early 2.x release that did not refuse it, it holds
both schemas, the old data and a new set written beside it. The report calls
that a split brain and lists the rows of each side, and the migration does not
merge them: deciding which side is right is for a person.

## From Python

The command is a thin layer over `beaver.migrate`: `plan_migration(path)`
for the dry run, and `migrate_database(source, destination)`, a coroutine,
for the copy. Both return a `MigrationReport` with the counts per collection,
and `format_report()` prints it as above.

```{python continue}
from beaver.migrate import plan_migration

report = plan_migration("old-desk.db")
print(type(report).__name__, report.legacy_version, report.dicts, report.lists)
```

## The program

A startup check for the desk: open the file, and if it is a 1.x one, say what
to do instead of failing with a traceback.

```{python export=examples/open_or_explain.py}
import sys

from beaver import BeaverDB, BeaverIncompatibleSchemaError, BeaverLegacySchemaError
from beaver.migrate import plan_migration


def open_desk(path: str) -> BeaverDB | None:
    try:
        return BeaverDB(path)
    except BeaverLegacySchemaError:
        report = plan_migration(path)
        rows = sum(report.dicts.values()) + sum(report.lists.values())
        print(f"{path} is a beaver {report.legacy_version} file with {rows} rows.")
        print(f"Run: beaver migrate {path} --output {path}.2x")
    except BeaverIncompatibleSchemaError as e:
        print(f"{path} was written by a newer beaver: {e}")
    return None


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "helpdesk.db"
    db = open_desk(path)
    if db is not None:
        with db:
            print(f"{path} is ready, {len(db.dict('settings'))} settings")


if __name__ == "__main__":
    main()
```

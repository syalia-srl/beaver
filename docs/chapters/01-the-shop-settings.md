# The shop's settings

```{python echo=false output=false}
# Each chapter starts from an empty database.
import glob, os

for f in glob.glob("helpdesk.db*"):
    os.remove(f)
```

The desk needs a few settings that outlive the program: the shop's name, its
opening hours, and the greeting that goes at the top of every reply. The first
version keeps them in a JSON file.

```{python continue}
import json
from pathlib import Path

SETTINGS = Path("settings.json")


def load():
    return json.loads(SETTINGS.read_text()) if SETTINGS.exists() else {}


def save(settings):
    SETTINGS.write_text(json.dumps(settings))


save({"shop": "Spoke & Chain", "hours": {"open": 9, "close": 18}})
print(load())
```

That works while one program touches the file. The desk has two: the web form
where customers write in, and the script the agents use. Both load the
settings, change one value, and save the whole file back.

```{python continue}
form = load()
agents = load()

form["greeting"] = "Thanks for writing to Spoke & Chain!"
agents["hours"]["close"] = 19

save(form)
save(agents)
print(load())
```

The greeting is gone. Each program wrote the whole file from its own copy, so
the second save erased the first one's change, and nothing failed. A crash in
the middle of `write_text` would be worse: half a file that `json.loads`
cannot read. The fix people reach for next is a lock file, then a temporary
file and a rename, and by then the settings file has become a small database.

## A dictionary in a file

`BeaverDB` opens a database file, creating it if it does not exist. Every kind
of data beaver keeps is reached through a method on it, and `db.dict(name)`
gives a dictionary with that name. It behaves like a Python `dict`, except
that every assignment is written to the file at once, one key at a time.

```{python continue}
SETTINGS.unlink()

from beaver import BeaverDB

db = BeaverDB("helpdesk.db")
settings = db.dict("settings")

settings["shop"] = "Spoke & Chain"
settings["hours"] = {"open": 9, "close": 18}
print(settings["shop"], settings["hours"], len(settings))
```

Values are anything JSON can hold: strings, numbers, lists, nested
dictionaries. A dictionary is a namespace inside the file, so `db.dict("settings")`
and `db.dict("agents")` never see each other's keys.

Now the two programs again. Each one opens its own `BeaverDB` on the same
file, as two processes would, and each writes only the key it changes.

```{python continue}
form = BeaverDB("helpdesk.db").dict("settings")
agents = BeaverDB("helpdesk.db").dict("settings")

form["greeting"] = "Thanks for writing to Spoke & Chain!"
hours = agents["hours"]
hours["close"] = 19
agents["hours"] = hours

print(dict(settings.items()))
```

Both changes are there. The greeting and the hours are separate rows, and
SQLite makes each write atomic, so a crash leaves either the old value or the
new one, never half of either.

## Reading what may be missing

Reading a key that is not there raises `KeyError`, as with a `dict`. `fetch`
returns a default instead, and `in`, `keys()`, `values()`, `items()`, `pop()`
and `delete()` work as you would expect.

```{python continue}
try:
    settings["holiday"]
except KeyError as e:
    print("KeyError:", e)

print(settings.fetch("holiday", "none planned"))
print("greeting" in settings, sorted(settings.keys()))
```

## Closing and reopening

`BeaverDB` runs a background thread that owns the SQLite connection. Close it
when you are done, or use it as a context manager, which closes it on the way
out. The values are in the file, so the next program that opens it finds
them.

```{python continue}
db.close()

with BeaverDB("helpdesk.db") as db:
    print(db.dict("settings")["hours"])
```

`beaver.connect(path)` does the same as `BeaverDB(path)`. It also accepts a
server URL, which chapter 14 uses to reach a database on another machine.

## The program

The settings module of the desk, as it stands after this chapter:

```{python export=examples/settings.py}
from beaver import BeaverDB

DEFAULTS = {
    "shop": "Spoke & Chain",
    "hours": {"open": 9, "close": 18},
    "greeting": "Thanks for writing to Spoke & Chain!",
}


def ensure_defaults(db: BeaverDB) -> None:
    settings = db.dict("settings")
    for key, value in DEFAULTS.items():
        if key not in settings:
            settings[key] = value


def main():
    with BeaverDB("helpdesk.db") as db:
        ensure_defaults(db)
        settings = db.dict("settings")
        hours = settings["hours"]
        print(f"{settings['shop']} is open {hours['open']}:00 to {hours['close']}:00")


if __name__ == "__main__":
    main()
```

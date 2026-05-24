# Migrating persistent lists from rc3 to rc4

`beaver-db 2.0rc4` changes the on-disk format of persistent lists.
`__beaver_lists__.item_order` was a `REAL` (float) column with a midpoint
insertion scheme that crashed after ~52 inserts at the same index. It is
now a `TEXT` (fractional-index string) column that does not collapse.

Databases created by `2.0rc3` or earlier are rejected on open by rc4 with
`BeaverIncompatibleSchemaError`. No automatic migration is provided. To
migrate your data:

## 1. With rc3 still installed, dump each list to JSON

```python
import json
import asyncio
from beaver import AsyncBeaverDB

async def dump(path: str, list_names: list[str], out: str):
    db = AsyncBeaverDB(path)
    await db.connect()
    try:
        result = {}
        for name in list_names:
            lst = db.list(name)
            result[name] = [item async for item in lst]
        with open(out, "w") as f:
            json.dump(result, f, indent=2)
    finally:
        await db.close()

asyncio.run(dump("old.db", ["queue", "todo", "..."], "lists.json"))
```

You must know the names of the lists you created — beaver does not enumerate
them. If you don't have them recorded, query the database directly:

```bash
sqlite3 old.db "SELECT DISTINCT list_name FROM __beaver_lists__"
```

## 2. Upgrade to rc4 and load into a fresh database

```python
import json
import asyncio
from beaver import AsyncBeaverDB

async def load(path: str, src: str):
    db = AsyncBeaverDB(path)
    await db.connect()
    try:
        data = json.load(open(src))
        for name, items in data.items():
            lst = db.list(name)
            for item in items:
                await lst.push(item)
    finally:
        await db.close()

asyncio.run(load("new.db", "lists.json"))
```

If your lists held Pydantic models, hand the model class to `db.list(name, Model)` and
serialize/deserialize accordingly — this script assumes JSON-roundtrippable values.

## 3. Verify, then swap

Sanity-check counts and a few values before retiring `old.db`. The dump
file `lists.json` is your backup until you do.

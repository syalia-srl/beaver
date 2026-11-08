# Attachments

```{python echo=false output=false}
import glob, os, shutil

for f in glob.glob("helpdesk.db*") + glob.glob("backup.db*") + glob.glob("*.jsonl"):
    os.remove(f)
shutil.rmtree("attachments", ignore_errors=True)
```

Customers send photos of the broken part, and agents attach invoices. The
first version writes the files to a folder and keeps their paths in a
dictionary:

```{python continue}
import shutil
from pathlib import Path

from beaver import BeaverDB

db = BeaverDB("helpdesk.db")
files = db.dict("attachments")

folder = Path("attachments/T-1001")
folder.mkdir(parents=True, exist_ok=True)
(folder / "brake.jpg").write_bytes(b"\xff\xd8\xff\xe0 (a photo of a brake)")
files["T-1001/brake.jpg"] = str(folder / "brake.jpg")
db.close()
```

Now the desk is backed up the way chapter 1 promised it could be, by copying
the database file, and the folder is lost with the old machine:

```{python continue}
shutil.copy("helpdesk.db", "backup.db")
shutil.rmtree("attachments")

with BeaverDB("backup.db") as restored:
    path = restored.dict("attachments")["T-1001/brake.jpg"]
    print(path, Path(path).exists())
```

The data now lives in two places, and every backup, copy, deletion and
permission has to treat both alike. Deleting a ticket's rows leaves its files
behind, and copying the files without the rows leaves paths that point
nowhere.

## Files in the database

`db.blob(name)` stores bytes under a key, with optional metadata, in the same
file as everything else. `put(key, data, metadata)` writes one, and
`blobs[key]` reads the bytes back. Keys are any string, so a path-like
`ticket/file` keeps them grouped.

```{python continue}
db = BeaverDB("helpdesk.db")
blobs = db.blob("attachments")

photo = b"\xff\xd8\xff\xe0 (a photo of a brake)"
blobs.put("T-1001/brake.jpg", photo, {"type": "image/jpeg", "from": "customer"})
blobs["T-1001/invoice.pdf"] = b"%PDF-1.7 (an invoice)"

print(blobs["T-1001/invoice.pdf"][:8], len(blobs), list(blobs.keys()))
```

`fetch(key)` returns a `BlobItem` with the `key`, the `data` and the
`metadata`. Only `bytes` are accepted: text goes in encoded.

```{python continue}
item = blobs.fetch("T-1001/brake.jpg")
print(item.key, item.metadata, len(item.data), "bytes")

try:
    blobs["T-1001/note.txt"] = "a string"
except TypeError as e:
    print("TypeError:", e)
```

`del blobs[key]`, `in`, `items()` and `clear()` work as for a dictionary. And
the backup is the copy of one file again:

```{python continue}
db.close()
shutil.copy("helpdesk.db", "backup.db")
with BeaverDB("backup.db") as restored:
    print(restored.blob("attachments").fetch("T-1001/brake.jpg").metadata)
```

SQLite stores a blob inline in its row, which suits photos and documents of
a few megabytes. Videos and disk images belong in object storage, with their
keys in beaver.

## Exporting a collection

Moving one collection to another database, or keeping a readable copy of it,
is `dump()` and `load()`. Dictionaries, lists, queues, logs, documents and
blobs have both. `dump(fp, format="jsonl")` writes one JSON line per item
(blob data is base64), and `load(fp, format="jsonl")` reads them back,
replacing what is there unless you pass `strategy="append"`.

```{python continue}
with BeaverDB("helpdesk.db") as db, open("attachments.jsonl", "w") as fp:
    db.blob("attachments").dump(fp, format="jsonl")

with BeaverDB("other.db") as other, open("attachments.jsonl") as fp:
    other.blob("attachments").load(fp, format="jsonl")
    print(sorted(other.blob("attachments").keys()))
```

Without a file, `dump()` returns the collection as a dictionary with
`metadata` and `items`. For blobs that form leaves the data out unless you
pass `payload=True`.

```{python echo=false output=false continue}
for f in glob.glob("other.db*") + glob.glob("backup.db*") + glob.glob("*.jsonl"):
    os.remove(f)
```

## The program

Attachments for the desk, with a size limit and a listing per ticket:

```{python export=examples/attachments.py}
from beaver import BeaverDB

MAX_BYTES = 10 * 1024 * 1024


def attach(db: BeaverDB, ticket: str, name: str, data: bytes, kind: str) -> str:
    if len(data) > MAX_BYTES:
        raise ValueError(f"{name} is larger than {MAX_BYTES} bytes")
    key = f"{ticket}/{name}"
    db.blob("attachments").put(key, data, {"type": kind, "size": len(data)})
    return key


def attachments_of(db: BeaverDB, ticket: str) -> list[tuple[str, int]]:
    blobs = db.blob("attachments")
    return [
        (key.split("/", 1)[1], blobs.fetch(key).metadata["size"])
        for key in blobs.keys()
        if key.startswith(f"{ticket}/")
    ]


def main():
    with BeaverDB("helpdesk.db") as db:
        db.blob("attachments").clear()
        attach(db, "T-1001", "brake.jpg", b"\xff\xd8 photo", "image/jpeg")
        attach(db, "T-1001", "invoice.pdf", b"%PDF-1.7 invoice", "application/pdf")
        attach(db, "T-1002", "chain.jpg", b"\xff\xd8 photo", "image/jpeg")
        for name, size in attachments_of(db, "T-1001"):
            print(f"{name}: {size} bytes")


if __name__ == "__main__":
    main()
```

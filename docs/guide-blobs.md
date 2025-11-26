# Blobs (File Store)

The `BlobManager` is designed for storing binary large objects (BLOBs) like images, PDFs, audio files, or zipped archives directly within the database.

While storing large files in a database is often discouraged in server-based systems (due to backup bloat), for a **local-first** application, it is often the correct choice. It keeps your data portable: a single `.db` file contains your entire application state, including assets, making backup and migration trivial.

## Quick Start

Initialize a blob store using `db.blobs()`.

```python
from beaver import BeaverDB

db = BeaverDB("app.db")
assets = db.blobs("user_assets")

# 1. Store a file
# You must pass 'bytes' to the put method.
with open("avatar.png", "rb") as f:
    assets.put("user_1_avatar.png", f.read())

# 2. Retrieve a file
data = assets.get("user_1_avatar.png")

if data:
    with open("downloaded_avatar.png", "wb") as f:
        f.write(data)
```

## Basic Operations

### Storing Files

Use `.put(key, data)` to save content. The `data` argument must be of type `bytes`.

```python
# Storing text as a blob (encode first)
assets.put("notes.txt", "Hello World".encode("utf-8"))
```

### Retrieving Files

Use `.get(key)` to retrieve the data. It returns `bytes` or `None` if the key does not exist.

```python
data = assets.get("notes.txt")
if data:
    print(data.decode("utf-8"))
```

### Storing Metadata

You can attach a JSON-serializable dictionary to any blob. This is useful for storing MIME types, original filenames, or upload timestamps without creating a separate dictionary entry.

```python
# Store image with metadata
assets.put(
    "photo_001.jpg",
    image_bytes,
    metadata={"content_type": "image/jpeg", "owner": "alice"}
)

# Retrieve metadata only (Fast)
# This avoids loading the full file content into memory.
meta = assets.metadata("photo_001.jpg")
print(meta["content_type"]) # -> "image/jpeg"
```

### Deleting Files

Remove blobs using `.delete(key)`.

```python
assets.delete("photo_001.jpg")
```

### Iteration

You can iterate over all keys in the blob store.

```python
# List all files
for filename in assets:
    print(f"Found file: {filename}")
```

## Advanced Features

### Bulk Uploads (Batching)

Inserting many small files one by one can be slow due to transaction overhead. Use `.batched()` to upload a directory of files in a single transaction.

> **Warning:** The batch is buffered in memory. Do not batch 100 video files at once, or you will run out of RAM. Use this for groups of small icons, documents, or config files.

```python
import os

# Bulk upload all icons
with assets.batched() as batch:
    for filename in os.listdir("./icons"):
        with open(f"./icons/{filename}", "rb") as f:
            batch.put(filename, f.read())
```

---
number: 12
title: "Add `.dump()` method for JSON export to all data managers"
state: open
labels:
---

## Tasks

- [ ] DictManager
- [ ] ListManager
- [ ] LogManager
- [ ] QueueManager
- [ ] CollectionManager
- [ ] BlobManager

### 1. Concept

This feature introduces a new public method, `.dump()`, to all primary data managers: `DictManager`, `ListManager`, `CollectionManager`, `LogManager`, `QueueManager`, and `BlobManager`.

The purpose of this method is to provide a simple, standardized way to export all data from a specific data structure into a single, portable JSON document. This functionality is essential for backups, debugging, and data migration.

The method will have two modes of operation:

1.  **Return Object:** If called with no arguments (`fp=None`), it will generate and return the complete data structure as a Python dictionary.
2.  **Write to File:** If passed a file-like object (e.g., an open file handle), it will serialize the data structure as a JSON string and write it directly to that object.

### 2. Use Cases

  * **Backups:** A user can easily create a JSON snapshot of a collection or dictionary for backup purposes.
  * **Debugging:** A developer can dump the entire contents of a list or queue to a file to inspect its state at a specific point in time.
  * **Migration:** Data can be dumped from one BeaverDB instance and programmatically loaded into another, or migrated to a different database system.
  * **Interoperability:** The JSON format allows data to be easily shared with other services, scripts, or front-end applications.

### 3. Proposed API

The same method signature will be added to all relevant manager classes.

```python
# In each manager class (e.g., beaver/dicts.py)
from typing import IO

class DictManager[T]:
    # ... existing methods ...

    def dump(self, fp: IO[str] | None = None) -> dict | None:
        """
        Dumps the entire contents of the dictionary to a JSON-compatible
        Python object or a file-like object.

        Args:
            fp: A file-like object opened in text mode (e.g., with 'w').
                If provided, the JSON dump will be written to this file.
                If None (default), the dump will be returned as a dictionary.

        Returns:
            A dictionary containing the dump if fp is None.
            None if fp is provided.
        """
        # ... implementation ...
```

#### Example 1: Writing to a JSON file

```python
db = BeaverDB("my_app.db")
config = db.dict("app_config")

with open("config_backup.json", "w", encoding="utf-8") as f:
    config.dump(f)

# config_backup.json now contains the full dump
```

#### Example 2: Getting as a Python object

```python
db = BeaverDB("my_app.db")
tasks = db.list("daily_tasks")

dump_data = tasks.dump()

print(f"Dumped {dump_data['metadata']['count']} tasks from {dump_data['metadata']['name']}")
```

### 4. Implementation Design

#### A. Standard JSON Output Structure

All dumps will adhere to the following top-level structure. The `count` field will be populated using the manager's `__len__()` method.

```json
{
  "metadata": {
    "database_path": "my_app.db",
    "type": "Dict",
    "name": "app_config",
    "count": 2,
    "dump_date": "2025-11-02T09:30:00.123456Z"
  },
  "items": [

  ]
}
```

  * `metadata.database_path`: The path to the `.db` file (e.g., "my\_app.db").
  * `metadata.type`: One of `Dict`, `List`, `Queue`, `Collection`, `Log`, or `BlobStore`.
  * `metadata.name`: The name of the manager (e.g., "app\_config").
  * `metadata.count`: The total number of items in the dump.
  * `metadata.dump_date`: An ISO 8601 timestamp in UTC.

#### B. Item Structure per Manager

The structure of the objects inside the `items` list will vary by manager:

  * **DictManager (`items`):** A list of key-value objects.

    ```json
    "items": [
      {"key": "theme", "value": "dark"},
      {"key": "user_id", "value": 123}
    ]
    ```

  * **ListManager (`items`):** A list of the items, in order.

    ```json
    "items": [
      {"id": "task-001", "desc": "Write report"},
      {"id": "task-002", "desc": "Deploy feature"}
    ]
    ```

  * **QueueManager (`items`):** A list of queue item objects, in priority order.

    ```json
    "items": [
      {"priority": 1, "timestamp": 1678886400.5, "data": {"action": "respond"}},
      {"priority": 10, "timestamp": 1678886402.1, "data": {"action": "backup"}}
    ]
    ```

  * **LogManager (`items`):** A list of log entry objects, in chronological order.

    ```json
    "items": [
      {"timestamp": 1678886400.5, "data": {"event": "login", "user": "alice"}},
      {"timestamp": 1678886402.1, "data": {"event": "logout", "user": "alice"}}
    ]
    ```

  * **CollectionManager (`items`):** A list of serialized `Document` objects.

    ```json
    "items": [
      {
        "id": "doc-001",
        "embedding": [0.1, 0.2, 0.3],
        "content": "This is a test document."
      }
    ]
    ```

    *(Note: The structure will be the result of `doc.to_dict(metadata_only=False)`)*

  * **BlobManager (`items`):** A list of blob objects, with binary data **base64 encoded**.

    ```json
    "items": [
      {
        "key": "avatars/user_1.png",
        "metadata": {"mimetype": "image/png"},
        "data_b64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
      }
    ]
    ```

#### C. Implementation Plan

1.  A private helper method, `_get_dump_object(self) -> dict`, will be added to each manager class. This method will query the database (using `self.items()`, `self[:]`, etc.) and format the Python dictionary.
2.  This helper will need access to the `db._db_path` from the core `BeaverDB` instance.
3.  It will use `datetime.now(timezone.utc).isoformat()` (requires `from datetime import datetime, timezone`).
4.  `BlobManager`'s helper will use `base64.b64encode(data).decode('utf-8')` (requires `import base64`).
5.  `QueueManager`'s helper will iterate over all items without popping them, likely using `self._db.connection.cursor()`.
6.  The public `dump(self, fp=None)` method will call `_get_dump_object()`.
7.  If `fp` is `None`, it returns the dictionary.
8.  If `fp` is provided, it uses `json.dump(dump_object, fp, indent=2)` (requires `import json`) and returns `None`.
9.  This new method will be added to:
      * `beaver/dicts.py` (`DictManager`)
      * `beaver/lists.py` (`ListManager`)
      * `beaver/queues.py` (`QueueManager`)
      * `beaver/logs.py` (`LogManager`)
      * `beaver/collections.py` (`CollectionManager`)
      * `beaver/blobs.py` (`BlobManager`)
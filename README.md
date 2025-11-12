<div style="text-align: center;">
  <img src="https://github.com/syalia-srl/beaver/blob/main/logo.png?raw=true" width="256px">
</div>

---

<!-- Project badges -->
![PyPI - Version](https://img.shields.io/pypi/v/beaver-db)
![PyPi - Python Version](https://img.shields.io/pypi/pyversions/beaver-db)
![Github - Open Issues](https://img.shields.io/github/issues-raw/syalia-srl/beaver)
![PyPi - Downloads (Monthly)](https://img.shields.io/pypi/dm/beaver-db)
![Github - Commits](https://img.shields.io/github/commit-activity/m/syalia-srl/beaver)

-----

`beaver` is a simple, local, and embedded database designed to manage complex, modern data types without requiring a database server, built on top of SQLite.

## Design Philosophy

`beaver` is built with a minimalistic philosophy for small, local use cases where a full-blown database server would be overkill.

  * **Minimal Dependencies**: The core library has minimal dependencies (`numpy`, `pydantic`, `rich`, `typer`). Advanced features (like the REST server) are optional extras.
  * **Safe Concurrency**: Thread-safe and multi-process-safe by default, with robust inter-process locking.
  * **Local-First**: A single, portable SQLite file is the default.
  * **Fast & Performant**: Zero network latency for local operations and an optional, in-memory read cache.
  * **Standard SQLite**: The database file is 100% compatible with any standard SQLite tool, ensuring data portability.
  * **Pythonic API**: Designed to feel like a natural extension of your code, using standard Python data structures and Pydantic models.

## Installation

Install the core library:

```bash
pip install beaver-db
```

To include optional features, you can install them as extras:

```bash
# For the REST API server and client
pip install "beaver-db[remote]"

# To install all optional features at once
pip install "beaver-db[full]"
```

### Docker

You can also run the BeaverDB REST API server using Docker.

```bash
docker pull ghcr.io/syalia-srl/beaver:latest
docker run -p 8000:8000 -v $(pwd)/data:/app ghcr.io/syalia-srl/beaver
```

## Quickstart

Get up and running in 30 seconds. This example showcases a dictionary, a list, and full-text search in a single script.

```python
from beaver import BeaverDB, Document

# 1. Initialize the database
db = BeaverDB("data.db")

# 2. Use a namespaced dictionary for app configuration
config = db.dict("app_config")
config["theme"] = "dark"
print(f"Theme set to: {config['theme']}")

# 3. Use a persistent list to manage a task queue
tasks = db.list("daily_tasks")
tasks.push("Write the project report")
tasks.push("Deploy the new feature")
print(f"First task is: {tasks[0]}")

# 4. Use a collection for document storage and search
articles = db.collection("articles")
doc = Document(
    id="sqlite-001",
    body="SQLite is a powerful embedded database ideal for local apps.",
)
articles.index(doc)

# Perform a full-text search
results = articles.match(query="database")
top_doc, rank = results[0]
print(f"FTS Result: '{top_doc.body}'")

db.close()
```

## Features

  * [**Key-Value Dictionaries**](https://syalia.com/beaver/guide-dicts-blobs.html): A Pythonic, dictionary-like interface for storing any JSON-serializable object or Pydantic model within separate namespaces. Includes TTL support for caching.
  * [**Blob Storage**](https://syalia.com/beaver/guide-dicts-blobs.html): A dictionary-like interface for storing binary data (e.g., images, PDFs) with associated JSON metadata.
  * [**Persistent Lists**](https://syalia.com/beaver/guide-lists-queues.html): A full-featured, persistent Python list supporting `push`, `pop`, `prepend`, `deque`, slicing, and in-place updates.
  * [**Persistent Priority Queue**](https://syalia.com/beaver/guide-lists-queues.html): A high-performance, persistent priority queue perfect for task orchestration across multiple processes.
  * [**Document Collections**](https://syalia.com/beaver/guide-collections.html): Store rich documents combining a vector embedding and Pydantic-based metadata.
  * [**Vector Search**](https://syalia.com/beaver/guide-collections.html%23vector-search): Fast, multi-process-safe linear vector search using an in-memory `numpy`-based index.
  * [**Full-Text & Fuzzy Search**](https://syalia.com/beaver/guide-collections.html%23full-text-fuzzy-search): Automatically index and search through document metadata using SQLite's FTS5 engine, with optional fuzzy search for typo-tolerant matching.
  * [**Knowledge Graph**](https://syalia.com/beaver/guide-collections.html%23knowledge-graph): Create directed, labeled relationships between documents and traverse the graph to find neighbors or perform multi-hop walks.
  * [**Pub/Sub System**](https://syalia.com/beaver/guide-realtime.html): A powerful, thread and process-safe publish-subscribe system for real-time messaging with a fan-out architecture.
  * [**Time-Indexed Logs**](https://syalia.com/beaver/guide-realtime.html): A specialized data structure for structured, time-series logs. Query historical data by time range or create a live, aggregated view.
  * [**Event-Driven Callbacks**](https://syalia.com/beaver/guide-realtime.html): Listen for database changes in real-time. Subscribe to events on specific managers (e.g., `db.collection("articles").on("index", ...)` or `db.dict("config").on("set", ...)` to trigger workflows or update UIs.
  * [**Inter-Process Locking**](https://syalia.com/beaver/guide-concurrency.html): Robust, deadlock-proof locks. Use `db.lock('task_name')` to coordinate arbitrary scripts, or `with db.list('my_list') as l:` to perform atomic, multi-step operations.
  * [**Pydantic Support**](https://syalia.com/beaver/dev-architecture.html%23type-safe-models): Optionally associate `pydantic.BaseModel`s with any data structure for automatic, recursive data validation and (de)serialization.
  * [**Deployment**](https://syalia.com/beaver/guide-deployment.html): Instantly serve your database over a RESTful API with `beaver serve` and interact with it via the `beaver` CLI.
  * [**Data Export & Backups**](https://syalia.com/beaver/guide-deployment.html): Dump any data structure to a portable JSON file with a single `.dump()` command.

## Documentation

For a complete API reference, in-depth guides, and more examples, please visit the official documentation at:

[**https://syalia.com/beaver**](https://syalia.com/beaver)

## Contributing

Contributions are welcome\! If you think of something that would make `beaver` more useful for your use case, please open an issue or submit a pull request.

## License

This project is licensed under the MIT License.
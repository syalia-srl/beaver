# beaver 🦫

A fast, single-file, multi-modal database for Python, built with the standard sqlite3 library.

`beaver` is the **B**ackend for **E**mbedded **A**synchronous **V**ector & **E**vent Retrieval. It's an industrious, all-in-one database designed to manage complex, modern data types without requiring a database server.

## Design Philosophy

`beaver` is built with a minimalistic philosophy for small, local use cases where a full-blown database server would be overkill.

  - **Minimalistic & Zero-Dependency**: Uses only Python's standard libraries (`sqlite3`, `asyncio`) and `numpy`.
  - **Async-First (When It Matters)**: The pub/sub system is fully asynchronous for high-performance, real-time messaging. Other features like key-value, list, and vector operations are synchronous for ease of use.
  - **Built for Local Applications**: Perfect for local AI tools, RAG prototypes, chatbots, and desktop utilities that need persistent, structured data without network overhead.
  - **Fast by Default**: It's built on SQLite, which is famously fast and reliable for local applications.

## Core Features

  - **Asynchronous Pub/Sub**: A fully asynchronous, Redis-like publish-subscribe system for real-time messaging.
  - **Persistent Key-Value Store**: A simple `set`/`get` interface for storing any JSON-serializable object.
  - **Pythonic List Management**: A fluent, Redis-like interface for managing persistent, ordered lists.
  - **Vector Storage & Search**: Store vector embeddings and perform simple, brute-force k-nearest neighbor searches, ideal for small-scale RAG.
  - **Single-File & Portable**: All data is stored in a single SQLite file, making it incredibly easy to move, back up, or embed in your application.

## Installation

```bash
pip install beaver-db
```

## Quickstart & API Guide

### Initialization

All you need to do is import and instantiate the `BeaverDB` class with a file path.

```python
from beaver import BeaverDB, Document

db = BeaverDB("my_application.db")
```

### Key-Value Store

Use `set()` and `get()` for simple data storage. The value can be any JSON-encodable object.

```python
# Set a value
db.set("app_config", {"theme": "dark", "user_id": 123})

# Get a value
config = db.get("app_config")
print(f"Theme: {config['theme']}") # Output: Theme: dark
```

### List Management

Get a list wrapper with `db.list()` and use Pythonic methods to manage it.

```python
tasks = db.list("daily_tasks")
tasks.push("Write the project report")
tasks.prepend("Plan the day's agenda")
print(f"The first task is: {tasks[0]}")
```

### Vector Storage & Search

Store `Document` objects containing vector embeddings and metadata. The search is a linear scan, which is sufficient for small-to-medium collections.

```python
# Get a handle to a collection
docs = db.collection("my_documents")

# Create and index a document (ID will be a UUID)
doc1 = Document(embedding=[0.1, 0.2, 0.7], text="A cat sat on the mat.")
docs.index(doc1)

# Create and index a document with a specific ID (for upserting)
doc2 = Document(id="article-42", embedding=[0.9, 0.1, 0.1], text="A dog chased a ball.")
docs.index(doc2)

# Search for the 2 most similar documents
query_vector = [0.15, 0.25, 0.65]
results = docs.search(vector=query_vector, top_k=2)

# Results are a list of (Document, distance) tuples
top_document, distance = results[0]
print(f"Closest document: {top_document.text} (distance: {distance:.4f})")
```

### Asynchronous Pub/Sub

Publish events from one part of your app and listen in another using `asyncio`.

```python
import asyncio

async def listener():
    async with db.subscribe("system_events") as sub:
        async for message in sub:
            print(f"LISTENER: Received event -> {message['event']}")

async def publisher():
    await asyncio.sleep(1)
    await db.publish("system_events", {"event": "user_login", "user": "alice"})

# To run them concurrently:
# asyncio.run(asyncio.gather(listener(), publisher()))
```

## Roadmap

`beaver` aims to be a complete, self-contained data toolkit. The following features are planned:

  - **More Efficient Vector Search**: Integrate an approximate nearest neighbor (ANN) index like `scipy.spatial.cKDTree` to improve search speed on larger datasets.
  - **JSON Document Store with Full-Text Search**: Store flexible JSON documents and get powerful full-text search across all text fields, powered by SQLite's FTS5 extension.
  - **Standard Relational Interface**: While `beaver` provides high-level features, you can always use the same SQLite file for normal relational tasks with standard SQL.

## License

This project is licensed under the MIT License.

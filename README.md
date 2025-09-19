# beaver 🦫

![PyPI - Downloads](https://img.shields.io/pypi/dm/beaver-db)
![PyPI](https://img.shields.io/pypi/v/beaver-db)
![License](https://img.shields.io/github/license/apiad/beaver)

A fast, single-file, multi-modal database for Python, built with the standard `sqlite3` library.

`beaver` is the **B**ackend for **E**mbedded, **A**ll-in-one **V**ector, **E**ntity, and **R**elationship storage. It's a simple, local, and embedded database designed to manage complex, modern data types without requiring a database server, built on top of SQLite.

## Design Philosophy

`beaver` is built with a minimalistic philosophy for small, local use cases where a full-blown database server would be overkill.

  - **Minimalistic & Zero-Dependency**: Uses only Python's standard libraries (`sqlite3`) and `numpy`/`scipy`.
  - **Synchronous & Thread-Safe**: Designed for simplicity and safety in multi-threaded environments.
  - **Built for Local Applications**: Perfect for local AI tools, RAG prototypes, chatbots, and desktop utilities that need persistent, structured data without network overhead.
  - **Fast by Default**: It's built on SQLite, which is famously fast and reliable for local applications. The vector search is accelerated with an in-memory k-d tree.
  - **Standard Relational Interface**: While `beaver` provides high-level features, you can always use the same SQLite file for normal relational tasks with standard SQL.

## Core Features

  - **Synchronous Pub/Sub**: A simple, thread-safe, Redis-like publish-subscribe system for real-time messaging.
  - **Namespaced Key-Value Dictionaries**: A Pythonic, dictionary-like interface for storing any JSON-serializable object within separate namespaces with optional TTL for cache implementations.
  - **Pythonic List Management**: A fluent, Redis-like interface for managing persistent, ordered lists, with all operations in constant time.
  - **Efficient Vector Storage & Search**: Store vector embeddings and perform fast approximate nearest neighbor searches using an in-memory k-d tree.
  - **Full-Text Search**: Automatically index and search through document metadata using SQLite's powerful FTS5 engine.
  - **Graph Traversal**: Create relationships between documents and traverse the graph to find neighbors or perform multi-hop walks.
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

### Namespaced Dictionaries

Use `db.dict()` to get a dictionary-like object for a specific namespace. The value can be any JSON-encodable object.

```python
# Get a handle to the 'app_config' namespace
config = db.dict("app_config")

# Set values using standard dictionary syntax
config["theme"] = "dark"
config["user_id"] = 123

# Get a value
theme = config.get("theme")
print(f"Theme: {theme}") # Output: Theme: dark
```

### List Management

Get a list wrapper with `db.list()` and use Pythonic methods to manage it.

```python
tasks = db.list("daily_tasks")
tasks.push("Write the project report")
tasks.prepend("Plan the day's agenda")
print(f"The first task is: {tasks[0]}")
```

### Vector & Text Search

Store `Document` objects containing vector embeddings and metadata. When you index a document, its string fields are automatically made available for full-text search.

```python
# Get a handle to a collection
docs = db.collection("articles")

# Create and index a multi-modal document
doc = Document(
    id="sql-001",
    embedding=[0.8, 0.1, 0.1],
    content="SQLite is a powerful embedded database ideal for local apps.",
    author="John Smith"
)
docs.index(doc)

# 1. Perform a vector search to find semantically similar documents
query_vector = [0.7, 0.2, 0.2]
vector_results = docs.search(vector=query_vector, top_k=3)
top_doc, distance = vector_results[0]
print(f"Vector Search Result: {top_doc.content} (distance: {distance:.2f})")

# 2. Perform a full-text search to find documents with specific words
text_results = docs.match(query="database", top_k=3)
top_doc, rank = text_results[0]
print(f"Full-Text Search Result: {top_doc.content} (rank: {rank:.2f})")

# 3. Combine both vector and text search for refined results
from beaver.collections import rerank
combined_results = rerank([d for d,_ in vector_results], [d for d,_ in text_results], weights=[2,1])
```

### Graph Traversal

Create relationships between documents and traverse them.

```python
from beaver import WalkDirection

# Create documents
alice = Document(id="alice", name="Alice")
bob = Document(id="bob", name="Bob")
charlie = Document(id="charlie", name="Charlie")

# Index them
social_net = db.collection("social")
social_net.index(alice)
social_net.index(bob)
social_net.index(charlie)

# Create edges
social_net.connect(alice, bob, label="FOLLOWS")
social_net.connect(bob, charlie, label="FOLLOWS")

# Find direct neighbors
following = social_net.neighbors(alice, label="FOLLOWS")
print(f"Alice follows: {[p.id for p in following]}")

# Perform a multi-hop walk to find friends of friends
foaf = social_net.walk(
    source=alice,
    labels=["FOLLOWS"],
    depth=2,
    direction=WalkDirection.OUTGOING,
)
print(f"Alice's extended network: {[p.id for p in foaf]}")
```

### Synchronous Pub/Sub

Publish events from one part of your app and listen in another using threads.

```python
import threading

def listener():
    for message in db.subscribe("system_events"):
        print(f"LISTENER: Received -> {message}")
        if message.get("event") == "shutdown":
            break

def publisher():
    db.publish("system_events", {"event": "user_login", "user": "alice"})
    db.publish("system_events", {"event": "shutdown"})

# Run them concurrently
listener_thread = threading.Thread(target=listener)
publisher_thread = threading.Thread(target=publisher)
listener_thread.start()
publisher_thread.start()
listener_thread.join()
publisher_thread.join()
```

## License

This project is licensed under the MIT License.
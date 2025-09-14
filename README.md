# beaver 🦫

A fast, single-file, multi-modal database for Python, built with the standard sqlite3 library.

`beaver` is the Backend for Embedded Asynchronous Vector & Event Retrieval. It's an industrious, all-in-one database designed to manage complex, modern data types without requiring a database server.

Design Philosophy
`beaver` is built with a minimalistic philosophy for small, local use cases where a full-blown database server would be overkill.

- **Minimalistic & Zero-Dependency**: Uses only Python's standard libraries (sqlite3, asyncio). No external packages are required, making it incredibly lightweight and portable.
- **Async-First (When It Matters)**: The pub/sub system is fully asynchronous for high-performance, real-time messaging. Simpler features like key-value and list operations remain synchronous for ease of use.
- **Built for Local Applications**: Perfect for local AI tools, chatbots (streaming tokens), task management apps, desktop utilities, and prototypes that need persistent, structured data without network overhead.
- **Fast by Default**: It's built on SQLite, which is famously fast, reliable, and will likely serve your needs for a long way before you need a "professional" database.

## Core Features

- **Asynchronous Pub/Sub**: A fully asynchronous, Redis-like publish-subscribe system for real-time messaging.
- **Persistent Key-Value Store**: A simple set/get interface for storing configuration, session data, or any other JSON-serializable object.
- **Pythonic List Management**: A fluent, Redis-like interface (db.list("name").push()) for managing persistent, ordered lists with support for indexing and slicing.
- **Single-File & Portable**: All data is stored in a single SQLite file, making it incredibly easy to move, back up, or embed in your application.

## Installation

```bash
pip install beaver-db
```

## Quickstart & API Guide

### 1. Initialization

All you need to do is import and instantiate the BeaverDB class with a file path.

```python
from beaver import BeaverDB

db = BeaverDB("my_application.db")
```

### 2. Key-Value Store

Use `set()` and `get()` for simple data storage. The value can be any JSON-encodable object.

```python
# Set a value
db.set("app_config", {"theme": "dark", "user_id": 123})

# Get a value
config = db.get("app_config")
print(f"Theme: {config['theme']}") # Output: Theme: dark
```

### 3. List Management

Get a list wrapper with `db.list()` and use Pythonic methods to manage it.

```python
# Get a wrapper for the 'tasks' list
tasks = db.list("daily_tasks")

# Push items to the list
tasks.push("Write the project report")
tasks.push("Send follow-up emails")
tasks.prepend("Plan the day's agenda") # Push to the front

# Use len() and indexing (including slices!)
print(f"There are {len(tasks)} tasks.")
print(f"The first task is: {tasks[0]}")
print(f"The rest is: {tasks[1:]}")
```

### 4. Asynchronous Pub/Sub

Publish events from one part of your app and listen in another using asyncio.

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

- **Vector Storage & Search**: Store NumPy vector embeddings and perform efficient k-nearest neighbor (k-NN) searches using `scipy.spatial.cKDTree`.
- **JSON Document Store with Full-Text Search**: Store flexible JSON documents and get powerful full-text search across all text fields, powered by SQLite's FTS5 extension.
- **Standard Relational Interface**: While `beaver` provides high-level features, you can always use the same SQLite file for normal relational tasks (e.g., managing users, products) with standard SQL.

## License

This project is licensed under the MIT License.

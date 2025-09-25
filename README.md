# beaver 🦫

<!-- Project badges -->
![PyPI - Version](https://img.shields.io/pypi/v/beaver-db)
![PyPi - Python Version](https://img.shields.io/pypi/pyversions/beaver-db)
![Github - Open Issues](https://img.shields.io/github/issues-raw/apiad/beaver)
![PyPi - Downloads (Monthly)](https://img.shields.io/pypi/dm/beaver-db)
![Github - Commits](https://img.shields.io/github/commit-activity/m/apiad/beaver)

A fast, single-file, multi-modal database for Python, built with the standard `sqlite3` library.

`beaver` is the **B**ackend for **E**mbedded, **A**ll-in-one **V**ector, **E**ntity, and **R**elationship storage. It's a simple, local, and embedded database designed to manage complex, modern data types without requiring a database server, built on top of SQLite.

## Design Philosophy

`beaver` is built with a minimalistic philosophy for small, local use cases where a full-blown database server would be overkill.

- **Minimalistic**: Uses only Python's standard libraries (`sqlite3`) and `numpy`/`faiss-cpu`.
- **Schemaless**: Flexible data storage without rigid schemas across all modalities.
- **Synchronous, Multi-Process, and Thread-Safe**: Designed for simplicity and safety in multi-threaded and multi-process environments.
- **Built for Local Applications**: Perfect for local AI tools, RAG prototypes, chatbots, and desktop utilities that need persistent, structured data without network overhead.
- **Fast by Default**: It's built on SQLite, which is famously fast and reliable for local applications. Vector search is accelerated with a high-performance, persistent `faiss` index.
- **Standard Relational Interface**: While `beaver` provides high-level features, you can always use the same SQLite file for normal relational tasks with standard SQL.

## Core Features

- **Sync/Async High-Efficiency Pub/Sub**: A powerful, thread and process-safe publish-subscribe system for real-time messaging with a fan-out architecture. Sync by default, but with an `as_async` wrapper for async applications.
- **Namespaced Key-Value Dictionaries**: A Pythonic, dictionary-like interface for storing any JSON-serializable object within separate namespaces with optional TTL for cache implementations.
- **Pythonic List Management**: A fluent, Redis-like interface for managing persistent, ordered lists.
- **Persistent Priority Queue**: A high-performance, persistent priority queue perfect for task orchestration across multiple processes. Also with optional async support.
- **Time-Indexed Log for Monitoring**: A specialized data structure for structured, time-series logs. Query historical data by time range or create a live, aggregated view of the most recent events for real-time dashboards.
- **Simple Blob Storage**: A dictionary-like interface for storing medium-sized binary files (like PDFs or images) directly in the database, ensuring transactional integrity with your other data.
- **High-Performance Vector Storage & Search**: Store vector embeddings and perform fast, crash-safe approximate nearest neighbor searches using a `faiss`-based hybrid index.
- **Full-Text and Fuzzy Search**: Automatically index and search through document metadata using SQLite's powerful FTS5 engine, enhanced with optional fuzzy search for typo-tolerant matching.
- **Knowledge Graph**: Create relationships between documents and traverse the graph to find neighbors or perform multi-hop walks.
- **Single-File & Portable**: All data is stored in a single SQLite file, making it incredibly easy to move, back up, or embed in your application.
- **Optional Type-Safety:** Although the database is schemaless, you can use a minimalistic typing system for automatic serialization and deserialization that is Pydantic-compatible out of the box.

## How Beaver is Implemented

BeaverDB is architected as a set of targeted wrappers around a standard SQLite database. The core `BeaverDB` class manages a single connection to the SQLite file and initializes all the necessary tables for the various features.

When you call a method like `db.dict("my_dict")` or `db.collection("my_docs")`, you get back a specialized manager object (`DictManager`, `CollectionManager`, etc.) that provides a clean, Pythonic API for that specific data modality. These managers translate the simple method calls (e.g., `my_dict["key"] = "value"`) into the appropriate SQL queries, handling all the complexity of data serialization, indexing, and transaction management behind the scenes. This design provides a minimal and intuitive API surface while leveraging the power and reliability of SQLite.

The vector store in BeaverDB is designed for high performance and reliability, using a hybrid faiss-based index that is both fast and persistent. Here's a look at the core ideas behind its implementation:

- **Hybrid Index System**: The vector store uses a two-tiered system to balance fast writes with efficient long-term storage:
- **Base Index**: A large, optimized faiss index that contains the majority of the vectors. This index is serialized and stored as a BLOB inside a dedicated SQLite table, ensuring it remains part of the single database file.
- **Delta Index**: A small, in-memory faiss index that holds all newly added vectors. This allows for near-instant write performance without having to rebuild the entire index for every new addition.
- **Crash-Safe Logging**: To ensure durability, all new vector additions and deletions are first recorded in a dedicated log table in the SQLite database. This means that even if the application crashes, no data is lost.
- **Automatic Compaction**: When the number of changes in the log reaches a certain threshold, a background process is automatically triggered to "compact" the index. This process rebuilds the base index, incorporating all the recent changes from the delta index, and then clears the log. This ensures that the index remains optimized for fast search performance over time.

This hybrid approach allows BeaverDB to provide a vector search experience that is both fast and durable, without sacrificing the single-file, embedded philosophy of the library.


## Installation

```bash
pip install beaver-db
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
    content="SQLite is a powerful embedded database ideal for local apps."
)
articles.index(doc)

# Perform a full-text search
results = articles.match(query="database")
top_doc, rank = results[0]
print(f"FTS Result: '{top_doc.content}'")

db.close()
```

## Things You Can Build with Beaver

Here are a few ideas to inspire your next project, showcasing how to combine Beaver's features to build powerful local applications.

### 1. AI Agent Task Management

Use a **persistent priority queue** to manage tasks for an AI agent. This ensures the agent always works on the most important task first, even if the application restarts.

```python
tasks = db.queue("agent_tasks")

# Tasks are added with a priority (lower is higher)
tasks.put({"action": "summarize_news"}, priority=10)
tasks.put({"action": "respond_to_user"}, priority=1)
tasks.put({"action": "run_backup"}, priority=20)

# The agent retrieves the highest-priority task
next_task = tasks.get() # -> Returns the "respond_to_user" task
print(f"Agent's next task: {next_task.data['action']}")
```

### 2. User Authentication and Profile Store

Use a **namespaced dictionary** to create a simple and secure user store. The key can be the username, and the value can be a dictionary containing the hashed password and other profile information.

```python
users = db.dict("user_profiles")

# Create a new user
users["alice"] = {
    "hashed_password": "...",
    "email": "alice@example.com",
    "permissions": ["read", "write"]
}

# Retrieve a user's profile
alice_profile = users.get("alice")
```

### 3. Chatbot Conversation History

A **persistent list** is perfect for storing the history of a conversation. Each time the user or the bot sends a message, just `push` it to the list. This maintains a chronological record of the entire dialogue.

```python
chat_history = db.list("conversation_with_user_123")

chat_history.push({"role": "user", "content": "Hello, Beaver!"})
chat_history.push({"role": "assistant", "content": "Hello! How can I help you today?"})

# Retrieve the full conversation
for message in chat_history:
    print(f"{message['role']}: {message['content']}")
```

### 4. Build a RAG (Retrieval-Augmented Generation) System

Combine **vector search** and **full-text search** to build a powerful RAG pipeline for your local documents. The vector search uses a high-performance, persistent `faiss` index that supports incremental additions without downtime.

```python
# Get context for a user query like "fast python web frameworks"
vector_results = [doc for doc, _ in docs.search(vector=query_vector)]
text_results = [doc for doc, _ in docs.match(query="python web framework")]

# Combine and rerank for the best context
from beaver.collections import rerank
best_context = rerank(vector_results, text_results, weights=[0.6, 0.4])
```

### 5. Caching for Expensive API Calls

Leverage a **dictionary with a TTL (Time-To-Live)** to cache the results of slow network requests. This can dramatically speed up your application and reduce your reliance on external services.

```python
api_cache = db.dict("external_api_cache")

# Check the cache first
response = api_cache.get("weather_new_york")
if response is None:
    # If not in cache, make the real API call
    response = make_slow_weather_api_call("New York")
    # Cache the result for 1 hour
    api_cache.set("weather_new_york", response, ttl_seconds=3600)
```

### 6. Real-time Event-Driven Systems

Use the **high-efficiency pub/sub system** to build applications where different components react to events in real-time. This is perfect for decoupled systems, real-time UIs, or monitoring services.

```python
# In one process or thread (e.g., a monitoring service)
system_events = db.channel("system_events")
system_events.publish({"event": "user_login", "user_id": "alice"})

# In another process or thread (e.g., a UI updater or logger)
with db.channel("system_events").subscribe() as listener:
    for message in listener.listen():
        print(f"Event received: {message}")
        # >> Event received: {'event': 'user_login', 'user_id': 'alice'}
```

### 7. Storing User-Uploaded Content

Use the simple blob store to save files like user avatars, attachments, or generated reports directly in the database. This keeps all your data in one portable file.

```python
attachments = db.blobs("user_uploads")

# Store a user's avatar
with open("avatar.png", "rb") as f:
    avatar_bytes = f.read()

attachments.put(
    key="user_123_avatar.png",
    data=avatar_bytes,
    metadata={"mimetype": "image/png"}
)

# Retrieve it later
avatar = attachments.get("user_123_avatar.png")
```

### 8. Real-time Application Monitoring

Use the **time-indexed log** to monitor your application's health in real-time. The `live()` method provides a continuously updating, aggregated view of your log data, perfect for building simple dashboards directly in your terminal.

```python
from datetime import timedelta
import statistics

logs = db.log("system_metrics")

def summarize(window):
    values = [log.get("value", 0) for log in window]
    return {"mean": statistics.mean(values), "count": len(values)}

live_summary = logs.live(
    window=timedelta(seconds=10),
    period=timedelta(seconds=1),
    aggregator=summarize
)

for summary in live_summary:
    print(f"Live Stats (10s window): Count={summary['count']}, Mean={summary['mean']:.2f}")
```

## Type-Safe Data Models

For enhanced data integrity and a better developer experience, BeaverDB supports type-safe operations for all modalities. By associating a model with these data structures, you get automatic serialization and deserialization, complete with autocompletion in your editor.

This feature is designed to be flexible and works seamlessly with two kinds of models:

  * **Pydantic Models**: If you're already using Pydantic, your `BaseModel` classes will work out of the box.
  * **Lightweight `beaver.Model`**: For a zero-dependency solution, you can inherit from the built-in `beaver.Model` class, which is a standard Python class with serialization methods automatically included.

Here’s a quick example of how to use it:

```python
from beaver import BeaverDB, Model

# Inherit from beaver.Model for a lightweight, dependency-free model
class User(Model):
    name: str
    email: str

db = BeaverDB("user_data.db")

# Associate the User model with a dictionary
users = db.dict("user_profiles", model=User)

# BeaverDB now handles serialization automatically
users["alice"] = User(name="Alice", email="alice@example.com")

# The retrieved object is a proper instance of the User class
retrieved_user = users["alice"]
print(f"Retrieved: {retrieved_user.name}") # Your editor will provide autocompletion here
```

In the same way you can have typed message payloads in `db.channel`, typed metadata in `db.blobs`, and custom document types in `db.collection`, as well as custom types in lists and queues.

Basically everywhere you can store or get some object in BeaverDB, you can use a typed version adding `model=MyClass` to the corresponding wrapper methond in `BeaverDB` and enjoy first-class type safety and inference.

## More Examples

For more in-depth examples, check out the scripts in the `examples/` directory:

  - [`async_pubsub.py`](examples/async_pubsub.py): A demonstration of the asynchronous wrapper for the publish/subscribe system.
  - [`blobs.py`](examples/blobs.py): Demonstrates how to store and retrieve binary data in the database.
  - [`cache.py`](examples/cache.py): A practical example of using a dictionary with TTL as a cache for API calls.
  - [`fts.py`](examples/fts.py): A detailed look at full-text search, including targeted searches on specific metadata fields.
  - [`fuzzy.py`](examples/fuzzy.py): Demonstrates fuzzy search capabilities for text search.
  - [`general_test.py`](examples/general_test.py): A general-purpose test to run all operations randomly which allows testing long-running processes and synchronicity issues.
  - [`graph.py`](examples/graph.py): Shows how to create relationships between documents and perform multi-hop graph traversals.
  - [`kvstore.py`](examples/kvstore.py): A comprehensive demo of the namespaced dictionary feature.
  - [`list.py`](examples/list.py): Shows the full capabilities of the persistent list, including slicing and in-place updates.
  - [`logs.py`](examples/logs.py): A short example showing how to build a realtime dashboard with the logging feature.
  - [`pqueue.py`](examples/pqueue.py): A practical example of using the persistent priority queue for task management.
  - [`producer_consumer.py`](examples/producer_consumer.py): A demonstration of the distributed task queue system in a multi-process environment.
  - [`publisher.py`](examples/publisher.py) and [`subscriber.py`](examples/subscriber.py): A pair of examples demonstrating inter-process message passing with the publish/subscribe system.
  - [`pubsub.py`](examples/pubsub.py): A demonstration of the synchronous, thread-safe publish/subscribe system in a single process.
  - [`rerank.py`](examples/rerank.py): Shows how to combine results from vector and text search for more refined results.
  - [`stress_vectors.py`](examples/stress_vectors.py): A stress test for the vector search functionality.
  - [`textual_chat.py`](examples/textual_chat.py): A chat application built with `textual` and `beaver` to illustrate the use of several primitives (lists, dicts, and channels) at the same time.
  - [`type_hints.py`](examples/type_hints.py): Shows how to use type hints with `beaver` to get better IDE support and type safety.
  - [`vector.py`](examples/vector.py): Demonstrates how to index and search vector embeddings, including upserts.

## Roadmap

`beaver` is roughly feature-complete, but there are still some features and improvements planned for future releases, mostly directed to improving developer experience.

These are some of the features and improvements planned for future releases:

  - **Async API**: Extend the async support with on-demand wrappers for all features besides channels.

Check out the [roadmap](roadmap.md) for a detailed list of upcoming features and design ideas.

If you think of something that would make `beaver` more useful for your use case, please open an issue and/or submit a pull request.

## License

This project is licensed under the MIT License.

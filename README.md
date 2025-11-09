<div style="text-align: center;">
  <img src="https://github.com/syalia-srl/beaver/blob/main/logo.png?raw=true" width="256px">
</div>

---

<!-- Project badges -->
![PyPI - Version](https://img.shields.io/pypi/v/beaver-db)
![PyPi - Python Version](https://img.shields.io/pypi/pyversions/beaver-db)
![Github - Open Issues](https://img.shields.io/github/issues-raw/apiad/beaver)
![PyPi - Downloads (Monthly)](https://img.shields.io/pypi/dm/beaver-db)
![Github - Commits](https://img.shields.io/github/commit-activity/m/apiad/beaver)

-----

> A fast, single-file, multi-modal database for Python, built with the standard `sqlite3` library.

`beaver` is the **B**ackend for **E**mbedded, **A**ll-in-one **V**ector, **E**ntity, and **R**elationship storage. It's a simple, local, and embedded database designed to manage complex, modern data types without requiring a database server, built on top of SQLite.

> If you like beaver's minimalist, no-bullshit philosophy, check out [castor](https://github.com/apiad/castor "null") for an equally minimalistic approach to task orchestration.

## Design Philosophy

`beaver` is built with a minimalistic philosophy for small, local use cases where a full-blown database server would be overkill.

  - **Minimalistic**: The core library has minimal dependencies (`numpy`, `rich`, `typer`). The REST server and client are available as an optional feature.
  - **Schemaless**: Flexible data storage without rigid schemas across all modalities.
  - **Synchronous, Multi-Process, and Thread-Safe**: Designed for simplicity and safety in multi-threaded and multi-process environments.
  - **Built for Local Applications**: Perfect for local AI tools, RAG prototypes, chatbots, and desktop utilities that need persistent, structured data without network overhead.
  - **Fast by Default**: It's built on SQLite, which is famously fast and reliable for local applications. Vector search is a built-in feature accelerated by a multi-process-safe, in-memory `numpy` index. It also features an optional, in-memory read cache. By setting `BeaverDB(cache_timeout=0.1)`, all reads are cached for 100ms, trading microsecond-level consistency for a massive boost in read-heavy applications by nearly eliminating database lookups.
  - **Standard Relational Interface**: While `beaver` provides high-level features, you can always use the same SQLite file for normal relational tasks with standard SQL.

## Core Features

  - **Sync/Async High-Efficiency Pub/Sub**: A powerful, thread and process-safe publish-subscribe system for real-time messaging with a fan-out architecture. Sync by default, but with an `as_async` wrapper for async applications.
  - **Namespaced Key-Value Dictionaries**: A Pythonic, dictionary-like interface for storing any JSON-serializable object within separate namespaces with optional TTL for cache implementations.
  - **Pythonic List Management**: A fluent, Redis-like interface for managing persistent, ordered lists.
  - **Persistent Priority Queue**: A high-performance, persistent priority queue perfect for task orchestration across multiple processes. Also with optional async support.
  - **Inter-Process Locking**: Two levels of robust, deadlock-proof locks. Use `db.lock('task_name')` to coordinate arbitrary scripts, or `with db.list('my_list') as l:` to perform atomic, multi-step operations on a specific data structure.
  - **Transparent Read Caching**: Optionally enable a high-speed, in-memory cache (`BeaverDB(cache_timeout=...)`) that trades millisecond-level consistency for instantaneous reads, drastically speeding up read-heavy applications.
  - **Time-Indexed Log for Monitoring**: A specialized data structure for structured, time-series logs. Query historical data by time range or create a live, aggregated view of the most recent events for real-time dashboards.
  - **Simple Blob Storage**: A dictionary-like interface for storing medium-sized binary files (like PDFs or images) directly in the database, ensuring transactional integrity with your other data.
  - **High-Performance Vector Storage & Search**: Store vector embeddings and perform fast, multi-process-safe linear searches using an in-memory `numpy`-based index.
  - **Full-Text and Fuzzy Search**: Automatically index and search through document metadata using SQLite's powerful FTS5 engine, enhanced with optional fuzzy search for typo-tolerant matching.
  - **Knowledge Graph**: Create relationships between documents and traverse the graph to find neighbors or perform multi-hop walks.
  - **Single-File & Portable**: All data is stored in a single SQLite file, making it incredibly easy to move, back up, or embed in your application.
  - **Built-in REST API Server (Optional)**: Instantly serve your database over a RESTful API with automatic OpenAPI documentation using FastAPI.
  - **Full-Featured CLI Client**: Interact with your database directly from the command line for administrative tasks and data exploration.
  - **First-Class Pydantic Support**: Optionally associate `pydantic.BaseModel`s with any data structure (`db.dict(model=User)`) for automatic, recursive data validation, serialization, and deserialization.
  - **Data Export & Backups:** Dump any dictionary, list, collection, queue, blob, or log structure to a portable JSON file with a single `.dump()` command.

## How Beaver is Implemented

BeaverDB is architected as a set of targeted wrappers around a standard SQLite database. The core `BeaverDB` class manages a single connection to the SQLite file and initializes all the necessary tables for the various features.

When you call a method like `db.dict("my_dict")` or `db.collection("my_docs")`, you get back a specialized manager object (`DictManager`, `CollectionManager`, etc.) that provides a clean, Pythonic API for that specific data modality. These managers translate the simple method calls (e.g., `my_dict["key"] = "value"`) into the appropriate SQL queries, handling all the complexity of data serialization, indexing, and transaction management behind the scenes. This design provides a minimal and intuitive API surface while leveraging the power and reliability of SQLite.

The vector store in BeaverDB is designed for simplicity and multi-process safety, using an in-memory `numpy` index with a log-based synchronization mechanism. Here's a look at the core ideas behind its implementation:

  - **In-Memory Delta-Index System**: Each process maintains its own in-memory `numpy` index. This index is split into two-tiers to balance fast writes with read efficiency:
  - **Base Index (`N-matrix`):** A `numpy` array holding the compacted, main set of vectors. This is loaded from disk once.
  - **Delta Index (`k-matrix`):** A small, in-memory `numpy` array holding all new vectors that have been added since the last compaction.
  - **Tombstones:** A set of deleted vector IDs that are filtered out at search time.
  - **Fast, Log-Based Sync**: All vector additions (`index()`) and deletions (`drop()`) are O(1) writes to a central SQLite log table (`_vector_change_log`). When another process performs a search, it first checks this log and performs a fast O(k) "delta-sync" to update its in-memory `k-matrix` and tombstones, rather than re-loading the entire N-matrix.
  - **Automatic Compaction**: When the delta index (`k-matrix`) grows too large, a compaction process is triggered to rebuild the main `N-matrix` from the database and clear the log. This ensures search performance remains fast over time.

This delta-index approach allows BeaverDB to provide a vector search experience that has extremely fast O(1) writes and O(k) cross-process synchronization, sacrificing O(log N) search time for a simpler, dependency-free O(N+k) linear scan. This aligns with the "simplicity-first" philosophy of the library.

## Installation

Install the core library:

```bash
pip install beaver-db
```

This includes `numpy` (for vector search) and `rich`/`typer` (for the CLI).

To include optional features, you can install them as extras:

```bash
# For the REST API server and client
pip install "beaver-db[remote]"

# To install all optional features at once
pip install "beaver-db[full]"
```

### Running with Docker

For a fully embedded and lightweight solution, you can run the BeaverDB REST API server using Docker. This is the easiest way to get a self-hosted instance up and running.

```bash
docker pull ghcr.io/syalia-srl/beaver:latest
docker run -p 8000:8000 -v $(pwd)/data:/app ghcr.io/syalia-srl/beaver
```

This command will start the BeaverDB server, and your database file will be stored in the data directory on your host machine. You can access the API at [http://localhost:8000](http://localhost:8000).

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

## Built-in Server and CLI

Beaver comes with a built-in REST API server and a powerful, full-featured command-line client, allowing you to interact with your database without writing any code.

### REST API Server

You can instantly expose all of your database's functionality over a RESTful API. This is perfect for building quick prototypes, microservices, or for interacting with your data from other languages.

**1. Start the server**

```bash
# Start the server for your database file
beaver serve --database data.db --port 8000
```

This starts a `FastAPI` server. You can now access the interactive API documentation at `http://127.0.0.1:8000/docs`.

**2. Interact with the API**

Here are a couple of examples using `curl`:

```bash
# Set a value in the 'app_config' dictionary
curl -X PUT http://127.0.0.1:8000/dicts/app_config/api_key \
     -H "Content-Type: application/json" \
     -d '"your-secret-api-key"'

# Get the value back
curl http://127.0.0.1:8000/dicts/app_config/api_key
# Output: "your-secret-api-key"
```

### Full-Featured CLI Client

The CLI client allows you to call any BeaverDB method directly from your terminal. Built with `typer` and `rich`, it provides a user-friendly, task-oriented interface with beautiful output.

```bash
# Get a value from a dictionary
beaver dict app_config get theme

# Set a value (JSON is automatically parsed)
beaver dict app_config set user '{"name": "Alice", "id": 123}'

# Push an item to a list
beaver list daily_tasks push "Review PRs"

# Watch a live, aggregated dashboard of a log
beaver log system_metrics watch

# Run a script protected by a distributed lock
beaver lock my-cron-job run bash -c 'run_daily_report.sh'
```

## Data Export for Backups

All data structures (`dict`, `list`, `collection`, `queue`, `log`, and `blobs`) support a `.dump()` method for easy backups and migration. You can either write the data directly to a JSON file or get it as a Python dictionary.

```python
import json
from beaver import BeaverDB

db = BeaverDB("my_app.db")
config = db.dict("app_config")

# Add some data
config["theme"] = "dark"
config["user_id"] = 456

# Dump the dictionary's contents to a JSON file
with open("config_backup.json", "w") as f:
    config.dump(f)

# 'config_backup.json' now contains:
# {
#   "metadata": {
#     "type": "Dict",
#     "name": "app_config",
#     "count": 2,
#     "dump_date": "2025-11-02T09:05:10.123456Z"
#   },
#   "items": [
#     {"key": "theme", "value": "dark"},
#     {"key": "user_id", "value": 456}
#   ]
# }

# You can also get the dump as a Python object
dump_data = config.dump()
```

You can also use the CLI to dump data:

```bash
beaver --database data.db collection my_documents dump > my_documents.json
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

### 2. Atomic Batch Processing

Ensure a worker process can safely pull a *batch* of items from a queue without another worker interfering, using the built-in manager lock.

```python
tasks_to_process = []
try:
    # This lock guarantees no other process can access 'agent_tasks'
    # while this block is running.
    with db.queue('agent_tasks').acquire(timeout=5) as q:
        for _ in range(10): # Get a batch of 10
            item = q.get(block=False)
            tasks_to_process.append(item.data)
except (TimeoutError, IndexError):
    # Lock timed out or queue was empty
    pass

# Now process the batch outside the lock
# process_batch(tasks_to_process)
```

### 3. User Authentication and Profile Store

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

### 4. Chatbot Conversation History

A **persistent list** is perfect for storing the history of a conversation. Each time the user or the bot sends a message, just `push` it to the list. This maintains a chronological record of the entire dialogue.

```python
chat_history = db.list("conversation_with_user_123")

chat_history.push({"role": "user", "content": "Hello, Beaver!"})
chat_history.push({"role": "assistant", "content": "Hello! How can I help you today?"})

# Retrieve the full conversation
for message in chat_history:
    print(f"{message['role']}: {message['content']}")
```

### 5. Build a RAG (Retrieval-Augmented Generation) System

Combine **vector search** and **full-text search** to build a powerful RAG pipeline for your local documents. The vector search uses a multi-process-safe, in-memory `numpy` index that supports incremental additions without downtime.

```python
# Get context for a user query like "fast python web frameworks"
vector_results = [doc for doc, _ in docs.search(vector=query_vector)]
text_results = [doc for doc, _ in docs.match(query="python web framework")]

# Combine and rerank for the best context
from beaver.collections import rerank
best_context = rerank(vector_results, text_results, weights=[0.6, 0.4])
```

### 6. Caching for Expensive API Calls

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

### 7. Real-time Event-Driven Systems

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

### 8. Storing User-Uploaded Content

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

### 9. Real-time Application Monitoring

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

### 10. Coordinate Distributed Web Scrapers

Run multiple scraper processes in parallel and use `db.lock()` to coordinate them. You can ensure only one process refreshes a shared API token or sitemap, preventing race conditions and rate-limiting.

```python
import time

scrapers_state = db.dict("scraper_state")

last_refresh = scrapers_state.get("last_sitemap_refresh", 0)
if time.time() - last_refresh > 3600: # Only refresh once per hour
    try:
        # Try to get a lock to refresh the shared sitemap, but don't wait long
        with db.lock("refresh_sitemap", timeout=1):
            # We got the lock. Check if it's time to refresh.
            print(f"PID {os.getpid()} is refreshing the sitemap...")
            scrapers_state["sitemap"] = ["/page1", "/page2"] # Your fetch_sitemap()
            scrapers_state["last_sitemap_refresh"] = time.time()

    except TimeoutError:
        # Another process is already refreshing, so we can skip
        print(f"PID {os.getpid()} letting other process handle refresh.")

# All processes can now safely use the shared sitemap
sitemap = scrapers_state.get("sitemap")
# ... proceed with scraping ...
```

## Type-Safe Data Models with Pydantic

For enhanced data integrity and a superior developer experience, BeaverDB has first-class support for Pydantic.

By associating a `pydantic.BaseModel` with a data structure, you get automatic, recursive (de)serialization and data validation, complete with autocompletion in your editor.

Here’s a quick example of how to use it:

```python
from pydantic import BaseModel
from beaver import BeaverDB

# Define your Pydantic model
class User(BaseModel):
    name: str
    email: str
    permissions: list[str]

db = BeaverDB("user_data.db")

# Associate the User model with a dictionary
users = db.dict("user_profiles", model=User)

# BeaverDB now handles serialization automatically
users["alice"] = User(
    name="Alice",
    email="alice@example.com",
    permissions=["read", "write"]
)

# The retrieved object is a proper, validated User instance
retrieved_user = users["alice"]

# Your editor will provide autocompletion here
print(f"Retrieved: {retrieved_user.name}")
print(f"Permissions: {retrieved_user.permissions}")
```

This works for all data structures: `db.dict`, `db.list`, `db.queue`, `db.log`, `db.channel`, and even the metadata in `db.blob` and `db.collection`.

## Documentation

For a complete API reference, in-depth guides, and more examples, please visit the official documentation at:

[**https://syalia.com/beaver**](https://syalia.com/beaver)

Also, check the [examples](./examples) folder for a comprehensive list of working examples using `beaver`.

## Roadmap

`beaver` is roughly feature-complete, but there are still some features and improvements planned for future releases, mostly directed to improving developer experience.

If you think of something that would make `beaver` more useful for your use case, please open an issue and/or submit a pull request.

## License

This project is licensed under the MIT License.
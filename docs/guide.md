# Feature Summary

This guide provides a comprehensive set of practical, code-first examples for every major feature of BeaverDB.

## Core Data Structures

### Key-Value Dictionaries (`db.dict`)

Use a namespaced dictionary for storing simple key-value data like application configuration or user profiles.

```python
from beaver import BeaverDB

db = BeaverDB("demo.db")

# Get a handle to a namespaced dictionary
config = db.dict("app_config")

# --- 1. Setting Values ---
config["theme"] = "dark"
config["retries"] = 3
config.set("user_ids", [101, 205, 301])

print(f"Configuration dictionary has {len(config)} items.")

# --- 2. Retrieving Values ---
theme = config["theme"]
print(f"Retrieved theme: {theme}")

non_existent = config.get("non_existent_key", "default_value")
print(f"Result for non_existent_key: {non_existent}")

# --- 3. Iterating Over the Dictionary ---
print("\nIterating over config items:")
for key, value in config.items():
    print(f"  - {key}: {value}")

# --- 4. Deleting an Item ---
del config["retries"]
print(f"\nAfter deleting 'retries', config has {len(config)} items.")

db.close()
```

### Caching with TTL (`db.dict`)

Leverage a dictionary with a **Time-To-Live (TTL)** to cache the results of slow network requests.

```python
import time
from beaver import BeaverDB

def expensive_api_call(prompt: str):
    """A mock function that simulates a slow API call."""
    print(f"--- Making expensive API call for: '{prompt}' ---")
    time.sleep(2)  # Simulate network latency
    return "Quito"

db = BeaverDB("demo.db")
api_cache = db.dict("api_cache")
prompt = "capital of Ecuador"

# --- 1. First Call (Cache Miss) ---
print("\nAttempt 1: Key is not in cache.")
response = api_cache.get(prompt)
if response is None:
    print("Cache miss.")
    response = expensive_api_call(prompt)
    # Set the value in the cache with a 10-second TTL
    api_cache.set(prompt, response, ttl_seconds=10)

print(f"Response: {response}")

# --- 2. Second Call (Cache Hit) ---
print("\nAttempt 2: Making the same request within 5 seconds.")
time.sleep(5)
response = api_cache.get(prompt)
if response is None:
    # ... (this won't be called) ...
    pass
else:
    print("Cache hit!")

print(f"Response: {response}")

# --- 3. Third Call (Cache Expired) ---
print("\nAttempt 3: Waiting for 12 seconds for the cache to expire.")
time.sleep(12)
response = api_cache.get(prompt)
if response is None:
    print("Cache miss (key expired).")
    response = expensive_api_call(prompt)
    api_cache.set(prompt, response, ttl_seconds=10)
else:
    print("Cache hit!")

print(f"Response: {response}")
db.close()
```

### Persistent Lists (`db.list`)

A persistent list is perfect for storing ordered data, like the history of a conversation. It supports a full Python list API.

```python
from beaver import BeaverDB

db = BeaverDB("demo.db")
tasks = db.list("project_tasks")

# --- 1. Pushing and Prepending Items ---
tasks.push({"id": "task-002", "desc": "Write documentation"})
tasks.push({"id": "task-003", "desc": "Deploy to production"})
tasks.prepend({"id": "task-001", "desc": "Design the feature"})

# --- 2. Iterating Over the List ---
print("\nCurrent tasks in order:")
for task in tasks:
    print(f"  - {task['id']}: {task['desc']}")

# --- 3. Accessing and Slicing ---
print(f"\nThe first task is: {tasks[0]}")
print(f"The last task is: {tasks[-1]}")
print(f"A slice of the first two tasks: {tasks[0:2]}")

# --- 4. Updating an Item in Place ---
print("\nUpdating the second task...")
tasks[1] = {"id": "task-002", "desc": "Write and review documentation"}
print(f"Updated second task: {tasks[1]}")

# --- 5. Deleting an Item by Index ---
print("\nDeleting the first task ('task-001')...")
del tasks[0]
print(f"List length after deletion: {len(tasks)}")

# --- 6. Popping the Last Item ---
last_item = tasks.pop()
print(f"\nPopped the last task: {last_item}")

db.close()
```

### Priority Queues (`db.queue`)

Use a persistent priority queue to manage tasks for an AI agent or any worker system. This ensures the most important tasks are always processed first.

```python
from beaver import BeaverDB

db = BeaverDB("demo.db")
tasks = db.queue("agent_tasks")

# Tasks are added with a priority (lower is higher)
tasks.put({"action": "summarize_news", "topic": "AI"}, priority=10)
tasks.put({"action": "respond_to_user", "user_id": "alice"}, priority=1)
tasks.put({"action": "run_backup", "target": "all"}, priority=20)
tasks.put({"action": "send_alert", "message": "CPU at 90%"}, priority=1)

# The agent retrieves the highest-priority task
# This is a blocking call that waits for an item
item1 = tasks.get() # -> Returns "respond_to_user" (priority 1, added first)
item2 = tasks.get() # -> Returns "send_alert" (priority 1, added second)
item3 = tasks.get() # -> Returns "summarize_news" (priority 10)

print(f"Agent's first task: {item1.data['action']}")
print(f"Agent's second task: {item2.data['action']}")

db.close()
```

### Blob Storage (`db.blob`)

Use the blob store to save binary data like user avatars, attachments, or generated reports directly in the database.

```python
from beaver import BeaverDB

db = BeaverDB("demo.db")
attachments = db.blob("user_uploads")

# Create some sample binary data
file_content = "This is the content of a virtual text file."
file_bytes = file_content.encode("utf-8")
file_key = "emails/user123/attachment_01.txt"

# Store a user's avatar with metadata
attachments.put(
    key=file_key,
    data=file_bytes,
    metadata={"mimetype": "text/plain", "sender": "alice@example.com"}
)

# Retrieve it later
blob = attachments.get(file_key)
if blob:
    print(f"Retrieved Blob: {blob.key}")
    print(f"Metadata: {blob.metadata}")
    print(f"Data (decoded): '{blob.data.decode('utf-8')}'")

# Delete the blob
attachments.delete(file_key)
print(f"\nVerified deletion: {file_key not in attachments}")

db.close()
```

## The Document Collection (`db.collection`)

The collection is the most powerful data structure, combining document storage with vector, text, and graph search.

### RAG System (Hybrid Search)

Combine **vector search** and **full-text search** to build a powerful RAG pipeline. The `rerank` helper function merges results from both.

```python
from beaver import BeaverDB, Document
from beaver.collections import rerank

db = BeaverDB("rag_demo.db")
articles = db.collection("articles")

# Index documents with both text and embeddings
docs_to_index = [
    Document(
        id="py-fast",
        embedding=[0.1, 0.9, 0.2],  # Vector leans towards "speed"
        body="Python is a great language for fast prototyping.",
    ),
    Document(
        id="py-data",
        embedding=[0.8, 0.2, 0.9],  # Vector leans towards "data science"
        body="The Python ecosystem is ideal for data science.",
    ),
    Document(
        id="js-fast",
        embedding=[0.2, 0.8, 0.1],  # Vector similar to "py-fast"
        body="JavaScript engines are optimized for fast execution.",
    ),
]
for doc in docs_to_index:
    articles.index(doc, fts=True) # Enable FTS

# 1. Vector Search for "high-performance code"
query_vector = [0.15, 0.85, 0.15] # A vector close to "fast"
vector_results = [doc for doc, _ in articles.search(vector=query_vector)]

# 2. Full-Text Search for "python"
text_results = [doc for doc, _ in articles.match(query="python")]

# 3. Combine and rerank to get the best context
best_context = rerank(text_results, vector_results)

print("--- Final Reranked Results ---")
for doc in best_context:
    print(f"  - {doc.id}: {doc.body}")

db.close()
```

### Knowledge Graphs (`db.collection`)

Connect documents together to form a graph, then find neighbors or perform multi-hop traversals.

```python
from beaver import BeaverDB, Document

db = BeaverDB("graph_demo.db")
net = db.collection("social_network")

# 1. Create Documents (nodes)
alice = Document(id="alice", body={"name": "Alice"})
bob = Document(id="bob", body={"name": "Bob"})
charlie = Document(id="charlie", body={"name": "Charlie"})
diana = Document(id="diana", body={"name": "Diana"})
net.index(alice); net.index(bob); net.index(charlie); net.index(diana)

# 2. Create Edges (relationships)
net.connect(alice, bob, label="FOLLOWS")
net.connect(alice, charlie, label="FOLLOWS")
net.connect(bob, diana, label="FOLLOWS")
net.connect(charlie, bob, label="FOLLOWS")

# 3. Find 1-hop neighbors
print("--- Testing `neighbors` (1-hop) ---")
following = net.neighbors(alice, label="FOLLOWS")
print(f"Alice follows: {[p.id for p in following]}")

# 4. Find multi-hop connections (e.g., "friends of friends")
print("\n--- Testing `walk` (multi-hop) ---")
foaf = net.walk(
    source=alice,
    labels=["FOLLOWS"],
    depth=2,
)
print(f"Alice's extended network (friends of friends): {[p.id for p in foaf]}")

db.close()
```


## Real-Time & Concurrency

### Inter-Process Locks (`db.lock`)

Run multiple scripts in parallel and use `db.lock()` to coordinate them. This example ensures only one process refreshes a shared resource, preventing race conditions.

```python
import time
import os
from beaver import BeaverDB

db = BeaverDB("scraper_state.db")
scrapers_state = db.dict("scraper_state")

last_refresh = scrapers_state.get("last_sitemap_refresh", 0)
if time.time() - last_refresh > 3600: # Only refresh once per hour
    try:
        # Try to get a lock, but don't wait long
        with db.lock("refresh_sitemap", timeout=1):
            # We got the lock.
            print(f"PID {os.getpid()} is refreshing the sitemap...")
            scrapers_state["sitemap"] = ["/page1", "/page2"] # Your fetch_sitemap()
            scrapers_state["last_sitemap_refresh"] = time.time()

    except TimeoutError:
        # Another process is already refreshing
        print(f"PID {os.getpid()} letting other process handle refresh.")

sitemap = scrapers_state.get("sitemap")
print(f"PID {os.getpid()} proceeding with sitemap: {sitemap}")
db.close()
```

### Atomic Batch Operations (`manager.acquire`)

Ensure a worker process can safely pull a *batch* of items from a queue without another worker interfering, using the built-in manager lock.

```python
from beaver import BeaverDB

db = BeaverDB("tasks.db")
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
    print("Could not get 10 items.")
    pass

# Now process the batch outside the lock
print(f"Processing batch of {len(tasks_to_process)} items.")
db.close()
```

### Pub/Sub Channels (`db.channel`)

Use the high-efficiency pub/sub system to build applications where components react to events in real-time.

```python
# --- In one process or thread (e.g., a monitoring service) ---
#
import time
from beaver import BeaverDB

db = BeaverDB("demo.db")
system_events = db.channel("system_events")
print("[Publisher] Publishing message...")
system_events.publish({"event": "user_login", "user_id": "alice"})
db.close()

# --- In another process or thread (e.g., a UI updater or logger) ---
#
from beaver import BeaverDB

db = BeaverDB("demo.db")
# The 'with' block handles the subscription lifecycle.
with db.channel("system_events").subscribe() as listener:
    for message in listener.listen():
        print(f"Event received: {message}")
        # >> Event received: {'event': 'user_login', 'user_id': 'alice'}
        break # Exit after one message for this example
db.close()
```

### Live-Aggregating Logs (`db.log`)

Monitor your application's health in real-time. The `.live()` method provides a continuously updating, aggregated view of your log data, perfect for terminal dashboards.

```python
from datetime import timedelta
import statistics
import time
from beaver import BeaverDB

db = BeaverDB("live_log_demo.db")
logs = db.log("system_metrics")

def summarize(window: list[dict]) -> dict:
    """Aggregator that calculates stats from a window of log data."""
    if not window:
        return {"mean": 0.0, "count": 0}
    values = [log.get("value", 0) for log in window]
    return {"mean": statistics.mean(values), "count": len(values)}

# Start a background thread to write logs (see examples/logs.py for full code)
# ...

# Get the live iterator over a 5-second rolling window, updating every 1 sec
live_summary = logs.live(
    window=timedelta(seconds=5),
    period=timedelta(seconds=1),
    aggregator=summarize
)

print("[Main Thread] Starting live view. Press Ctrl+C to stop.")
try:
    for summary in live_summary:
        print(f"Live Stats (5s window): Count={summary['count']}, Mean={summary['mean']:.2f}")
        time.sleep(1) # In a real app, this loop just blocks
except KeyboardInterrupt:
    print("\nShutting down.")
finally:
    db.close()
```

### Event-Driven Callbacks (`.on` / `.off`)

Listen for database changes in real-time. You can subscribe to events on specific managers (e.g., `db.dict("config").on("set", ...)` to trigger workflows or update UIs).

```python
import time
from beaver import BeaverDB

db = BeaverDB("events_demo.db")
config = db.dict("app_config")
config.clear()

def on_config_change(payload):
    """This callback is triggered when a key is set or deleted."""
    print(f"EVENT RECEIVED: Key '{payload['key']}' was changed!")

# Subscribe to 'set' events on this specific dict
set_handle = config.on("set", on_config_change)
del_handle = config.on("del", on_config_change)

# Give the listener thread time to start
time.sleep(0.1)

print("Setting 'theme'...")
config["theme"] = "dark"  # Triggers the 'on_config_change' callback
time.sleep(0.1) # Wait for event to process

print("Deleting 'theme'...")
del config["theme"] # Triggers the 'on_config_change' callback
time.sleep(0.1)

# Clean up the listeners
set_handle.off()
del_handle.off()

print("Listeners are off. This change will be silent.")
config["theme"] = "light" # No event will be printed
time.sleep(0.1)

db.close()
```


## Advanced Features

### Type-Safe Models with Pydantic

BeaverDB has first-class support for Pydantic. By associating a `BaseModel` with a data structure, you get automatic, recursive (de)serialization and data validation.

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

db.close()
```

### Server & CLI

You can instantly expose your database over a RESTful API and interact with it from the command line.

**1. Start the Server**

```bash
# Start the server for your database file
beaver serve --database data.db --port 8000
```

**2. Interact with the API (e.g., from `curl`)**

```bash
# Set a value in the 'app_config' dictionary
curl -X PUT http://127.0.0.1:8000/dicts/app_config/api_key \
     -H "Content-Type: application/json" \
     -d '"your-secret-api-key"'

# Get the value back
curl http://127.0.0.1:8000/dicts/app_config/api_key
# Output: "your-secret-api-key"
```

**3. Interact with the CLI Client**

The `beaver` CLI lets you call any method directly from your terminal.

```bash
# Get a value from a dictionary
beaver --database data.db dict app_config get theme

# Set a value (JSON is automatically parsed)
beaver --database data.db dict app_config set user '{"name": "Alice", "id": 123}'

# Push an item to a list
beaver --database data.db list daily_tasks push "Review PRs"

# Run a script protected by a distributed lock
beaver --database data.db lock my-cron-job run bash -c 'run_daily_report.sh'
```

### Data Export & Backups (`.dump`)

All data structures support a `.dump()` method for easy backups and migration to a JSON file.

```python
import json
from beaver import BeaverDB

db = BeaverDB("my_app.db")
config = db.dict("app_config")
config["theme"] = "dark"
config["user_id"] = 456

# Dump the dictionary's contents to a JSON file
with open("config_backup.json", "w") as f:
    config.dump(f)

# You can also get the dump as a Python object
dump_data = config.dump()
print(dump_data['metadata'])

db.close()
```

You can also use the CLI to dump data:

```bash
beaver --database data.db collection my_documents dump > my_documents.json
```
# beaver 🦫

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
  - **Pythonic List Management**: A fluent, Redis-like interface for managing persistent, ordered lists.
  - **Persistent Priority Queue**: A high-performance, persistent queue that always returns the item with the highest priority, perfect for task management.
  - **Efficient Vector Storage & Search**: Store vector embeddings and perform fast approximate nearest neighbor searches using an in-memory k-d tree.
  - **Full-Text Search**: Automatically index and search through document metadata using SQLite's powerful FTS5 engine.
  - **Graph Traversal**: Create relationships between documents and traverse the graph to find neighbors or perform multi-hop walks.
  - **Single-File & Portable**: All data is stored in a single SQLite file, making it incredibly easy to move, back up, or embed in your application.

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

Combine **vector search** and **full-text search** to build a powerful RAG pipeline for your local documents.

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

## More Examples

For more in-depth examples, check out the scripts in the `examples/` directory:

  - [`examples/kvstore.py`](https://www.google.com/search?q=%5Bhttps://www.google.com/search%3Fq%3Dexamples/kvstore.py%5D\(https://www.google.com/search%3Fq%3Dexamples/kvstore.py\)): A comprehensive demo of the namespaced dictionary feature.
  - [`examples/list.py`](https://www.google.com/search?q=%5Bhttps://www.google.com/search%3Fq%3Dexamples/list.py%5D\(https://www.google.com/search%3Fq%3Dexamples/list.py\)): Shows the full capabilities of the persistent list, including slicing and in-place updates.
  - [`examples/queue.py`](https://www.google.com/search?q=%5Bhttps://www.google.com/search%3Fq%3Dexamples/queue.py%5D\(https://www.google.com/search%3Fq%3Dexamples/queue.py\)): A practical example of using the persistent priority queue for task management.
  - [`examples/vector.py`](https://www.google.com/search?q=%5Bhttps://www.google.com/search%3Fq%3Dexamples/vector.py%5D\(https://www.google.com/search%3Fq%3Dexamples/vector.py\)): Demonstrates how to index and search vector embeddings, including upserts.
  - [`examples/fts.py`](https://www.google.com/search?q=%5Bhttps://www.google.com/search%3Fq%3Dexamples/fts.py%5D\(https://www.google.com/search%3Fq%3Dexamples/fts.py\)): A detailed look at full-text search, including targeted searches on specific metadata fields.
  - [`examples/graph.py`](https://www.google.com/search?q=%5Bhttps://www.google.com/search%3Fq%3Dexamples/graph.py%5D\(https://www.google.com/search%3Fq%3Dexamples/graph.py\)): Shows how to create relationships between documents and perform multi-hop graph traversals.
  - [`examples/pubsub.py`](https://www.google.com/search?q=%5Bhttps://www.google.com/search%3Fq%3Dexamples/pubsub.py%5D\(https://www.google.com/search%3Fq%3Dexamples/pubsub.py\)): A demonstration of the synchronous, thread-safe publish/subscribe system.
  - [`examples/cache.py`](https://www.google.com/search?q=%5Bhttps://www.google.com/search%3Fq%3Dexamples/cache.py%5D\(https://www.google.com/search%3Fq%3Dexamples/cache.py\)): A practical example of using a dictionary with TTL as a cache for API calls.
  - [`examples/rerank.py`](https://www.google.com/search?q=%5Bhttps://www.google.com/search%3Fq%3Dexamples/rerank.py%5D\(https://www.google.com/search%3Fq%3Dexamples/rerank.py\)): Shows how to combine results from vector and text search for more refined results.

## Roadmap

These are some of the features and improvements planned for future releases:

  - **Fuzzy search**: Implement fuzzy matching capabilities for text search.
  - **Faster ANN**: Explore integrating more advanced ANN libraries like `faiss` for improved vector search performance.
  - **Improved Pub/Sub**: Fan-out implementation with a more Pythonic API.
  - **Async API**: Comprehensive async support with on-demand wrappers for all collections.

Check out the [roadmap](https://www.google.com/search?q=roadmap.md) for a detailed list of upcoming features and design ideas.

## License

This project is licensed under the MIT License.

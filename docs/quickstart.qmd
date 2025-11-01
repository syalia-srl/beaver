# Quickstart Guide

This is where the fun begins. Let's get BeaverDB installed and run your first multi-modal script. You'll be up and running in about 30 seconds.

## Installation

BeaverDB is a Python library, so you can install it right from your terminal using pip.

**The Core Install**

If you just want the core features—like key-value dictionaries, lists, and queues—you can install the zero-dependency package.

```bash
# This has NO external dependencies
pip install beaver-db
```

This gives you all the core data structures and is perfect for many simple applications.

**Installing Optional Features**

BeaverDB keeps its core light by making advanced features optional. You can install them as "extras" as needed.

- `beaver-db[vector]`: Adds AI-powered vector search (using faiss).
- `beaver-db[server,cli]`: Adds the fastapi-based REST server and the beaver command-line tool.

For this guide, we recommend installing the `beaver-db[full]` package, which includes everything, so you can follow along with all the examples.

```bash
# To install all features, including vector search and the server
pip install "beaver-db[full]"
```

With that, you're ready to write some code.

## Your First Example in 10 Lines

Let's create a single Python script that shows off BeaverDB's "multi-modal" power. We'll use three different data types—a dictionary, a list, and a document collection—all in the same database file.

Create a new file named `quickstart.py` and add the following:

```python
from beaver import BeaverDB, Document

# 1. Initialize the database
# This creates a single file "my_data.db" if it doesn't exist
# and sets it up for safe, concurrent access.
db = BeaverDB("my_data.db")

# 2. Use a namespaced dictionary (like a Python dict)
# This is perfect for storing app configuration or user settings.
config = db.dict("app_config")
config["theme"] = "dark"
config["user_id"] = 123

# You can read the value back just as easily:
print(f"App theme is: {config['theme']}")

# 3. Use a persistent list (like a Python list)
# This is great for a to-do list, a job queue, or a chat history.
tasks = db.list("daily_tasks")
tasks.push({"id": "task-001", "desc": "Write project report"})
tasks.push({"id": "task-002", "desc": "Deploy new feature"})

# You can access items by index, just like a normal list:
print(f"First task is: {tasks[0]['desc']}")

# 4. Use a collection for rich documents and search
# This is the most powerful feature, combining data and search.
articles = db.collection("articles")

# Create a Document to store.
# We give it a unique ID and some text content.
doc = Document(
    id="sqlite-001",
    content="SQLite is a powerful embedded database ideal for local apps."
)

# 5. Index the document
# This not only saves the document but also automatically
# makes its text content searchable via a Full-Text Search (FTS) index
# with optional fuzzy matching.
articles.index(doc, fts=True, fuzzy=True)

# 6. Perform a full-text search
# This isn't a simple string find; it's a real search engine with fuzzy matching!
results = articles.match(query="datbase", fuzziness=1)

# The result is a list of tuples: (document, score)
top_doc, rank = results[0]
print(f"Search found: '{top_doc.content}' (Score: {rank:.2f})")
```

Here’s a line-by-line explanation of what you just did:

* **`from beaver import BeaverDB, Document`**
    `BeaverDB` is the main class, your entry point to the database. A `Document` is a special data object used when you're working with `db.collection()`.

* **`db = BeaverDB("my_data.db")`**
    This is the most important line. It finds `my_data.db` or creates it if it's not there. It also automatically enables all the high-performance and safety features (like Write-Ahead Logging) so it's ready for use.

* **`config = db.dict("app_config")`**
    Here, you're asking BeaverDB for a dictionary. `"app_config"` is the "namespace." This means you can have *many* different dictionaries (`app_config`, `user_prefs`, `cache`, etc.) that won't interfere with each other. The `config` object you get back behaves just like a standard Python `dict`. When you do `config["theme"] = "dark"`, that change is instantly saved to the `my_data.db` file.

* **`tasks = db.list("daily_tasks")`**
    Same idea, but for a list. You get back a `tasks` object that acts like a Python `list`. You can `push` (append) items, get items by index (`tasks[i]`), or `pop` them. You can also insert and remove items at an arbitrary index, and it all works instantaneously (in CS terms, it's O(1) for all operations).

* **`articles = db.collection("articles")`**
    This gets you a "collection," which is the most powerful data structure. A collection is designed to hold rich data, like articles, user profiles, or AI embeddings.

* **`doc = Document(...)`**
    To put something in a collection, you wrap it in a `Document`. Here, we give it a unique `id` and some `content`. You can add any other fields you want just by passing them as keyword arguments.

* **`articles.index(doc, ...)`**
    This is where the magic happens. When you call `.index()`, BeaverDB saves your document. But it *also* reads the `content` field and automatically puts all the words into a Full-Text Search (FTS) index and a clever fuzzy index, which are optional.

* **`results = articles.match(query="database")`**
    This line runs a search. Because `index()` already did the work, this query is fast. It searches the FTS index for the word "database" and finds your document.

When you run the script, you've created a single `my_data.db` file that now contains your config, your task list, and your searchable articles.

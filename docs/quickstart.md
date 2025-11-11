# Quickstart Guide

This is where the fun begins. Let's get BeaverDB installed and run your first multi-modal script. You'll be up and running in about 30 seconds.

## Installation

BeaverDB is a Python library, so you can install it right from your terminal using `uv` or `pip`.

**The Core Install**

The core `beaver-db` package includes everything you need for local development, including the CLI, vector search, and all data structures.

```bash
# This includes the core library, vector search, and the CLI
pip install beaver-db
```

**Installing Optional Features**

The only optional feature is the REST API server, which allows you to run BeaverDB as a networked service.

  - `beaver-db[remote]`: Adds the `fastapi`-based REST server, which you can run with the `beaver serve` command.
  - `beaver-db[full]`: A convenience extra that includes `remote` and all future optional features.

```bash
# To install all features, including the REST server
pip install "beaver-db[full]"
```

## Docker

You can also run the BeaverDB REST API server using Docker. This is the recommended way to deploy BeaverDB as a service.

```bash
# Pull the latest image from the GitHub Container Registry
docker pull ghcr.io/syalia-srl/beaver:latest

# Run the server, mounting a local directory to persist data
docker run -p 8000:8000 \
  -v $(pwd)/my-beaver-data:/app/data \
  -e "DATABASE=data/production.db" \
  ghcr.io/syalia-srl/beaver:latest
```

This command:

  - Runs the server on port 8000.
  - Mounts a local folder named `my-beaver-data` into the container.
  - Tells the server to create its database file at `/app/data/production.db` (which will persist in your `my-beaver-data` folder).

## A Step-by-Step Example

Let's create a single Python script that shows off BeaverDB's "multi-modal" power.

Create a new file named `quickstart.py`.

### 1. Initialize the Database

First, import `BeaverDB` and `Document`. The `BeaverDB` class is your main entry point, and `Document` is the object we'll use for storing rich data. This line creates a single file, `my_data.db`, if it doesn't already exist.

```python
from beaver import BeaverDB, Document

# This creates a single file "my_data.db" if it doesn't exist
# and sets it up for safe, concurrent access.
db = BeaverDB("my_data.db")
```

### 2. Use a Dictionary

Now let's use a namespaced dictionary. This is perfect for storing app configuration or user settings. We get it by calling `db.dict("app_config")`. The object it returns behaves just like a standard Python `dict`.

```python
# This is perfect for storing app configuration or user settings.
config = db.dict("app_config")

# Assigning a value saves it instantly to the database file.
config["theme"] = "dark"
config["user_id"] = 123

# You can read the value back just as easily:
print(f"App theme is: {config['theme']}")
```

### 3. Use a Persistent List

Next, let's store some ordered data. A persistent list (`db.list()`) is great for a to-do list, a job queue, or a chat history. It supports methods like `push`, `pop`, and standard index access.

```python
# This is great for a to-do list, a job queue, or a chat history.
tasks = db.list("daily_tasks")

# Use .push() to append items
tasks.push({"id": "task-001", "desc": "Write project report"})
tasks.push({"id": "task-002", "desc": "Deploy new feature"})

# You can access items by index, just like a normal list:
print(f"First task is: {tasks[0]['desc']}")
```

### 4. Use a Collection

The "collection" is the most powerful feature. It stores rich `Document` objects and allows you to search them using vectors, text, or graph relationships.

Let's get a collection and create a `Document` to store. The `body` field holds all of our text and metadata.

```python
# This is the most powerful feature, combining data and search.
articles = db.collection("articles")

# Create a Document to store.
# We give it a unique ID and some text content in the 'body'.
doc = Document(
    id="sqlite-001",
    body="SQLite is a powerful embedded database ideal for local apps."
)
```

### 5. Index for Search

Now, we'll save the document using `.index()`. By setting `fts=True`, we tell BeaverDB to *also* automatically add the text in `body` to a Full-Text Search index. We'll add `fuzzy=True` to tolerate typos.

```python
# This not only saves the document but also automatically
# makes its text content searchable via a Full-Text Search (FTS) index
# with optional fuzzy matching.
articles.index(doc, fts=True, fuzzy=True)
```

### 6. Perform a Fuzzy Search

Finally, let's query our collection. We'll use `.match()` to perform a text search. Notice the intentional typo in **"datbase"**. Because we indexed with `fuzziness=1`, BeaverDB finds the correct document anyway\!

```python
# This isn't a simple string find; it's a real search engine!
# Note the typo in "datbase"
results = articles.match(query="datbase", fuzziness=1)

# The result is a list of tuples: (document, score)
top_doc, rank = results[0]
print(f"Search found: '{top_doc.body}' (Score: {rank:.2f})")
```

When you run your `quickstart.py` script, you'll have a single `my_data.db` file containing your config, your task list, and your searchable articles.

## Using the CLI

The `beaver` CLI is included in the core installation and is a great way to inspect or manage your database from the terminal.

Let's interact with the `my_data.db` file we just created.

```bash
# Get the 'theme' key from the 'app_config' dictionary
$ beaver --database my_data.db dict app_config get theme
"dark"

# Run the same fuzzy search from our script
$ beaver --database my_data.db collection articles match "datbase" --fuzziness 1
[
  {
    "document": {
      "id": "sqlite-001",
      "embedding": null,
      "body": "SQLite is a powerful embedded database ideal for local apps."
    },
    "score": 0.0
  }
]
```

## Running the REST API Server

You can start a REST API server for your database using the `beaver serve` command. This allows you to interact with your BeaverDB instance over HTTP, making it easy to build web or mobile applications.

```bash
$ beaver serve --database my_data.db --port 8000
INFO:     Started server process [12345]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

Now you can access your database via HTTP requests. For example, to get the `theme` from the `app_config` dictionary:

```bash
$ curl http://localhost:8000/dict/app_config/theme
"dark"
```

That's it! You've successfully installed BeaverDB, created a multi-modal database, and interacted with it both programmatically and via the CLI and REST API.

Happy coding!

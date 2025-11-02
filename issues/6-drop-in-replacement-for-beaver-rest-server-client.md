---
number: 6
title: "Drop-in replacement for Beaver REST server client"
state: open
labels:
- enhancement
---

### 1. Concept

This feature introduces a new `BeaverClient` class that acts as a **drop-in replacement** for the core `BeaverDB` class. Instead of interacting directly with a local SQLite file, this client will execute all operations by making requests to a remote BeaverDB REST API server. This allows users to seamlessly switch from a local, embedded database to a client-server architecture without changing their application code.

### 2. Use Cases

* **Seamless Scaling**: Effortlessly transition a project from a local prototype to a networked service without a code rewrite.
* **Multi-Process/Multi-Machine Access**: Allow multiple processes or machines to share and interact with a single, centralized BeaverDB instance.
* **Language Interoperability**: While the client itself is Python, it provides a blueprint for creating clients in other languages to interact with the BeaverDB server.

### 3. Proposed API

The API is designed for maximum compatibility. A user only needs to change how the database object is instantiated.

**Local Implementation:**

```python
from beaver import BeaverDB
db = BeaverDB("my_local_data.db")
```

**Remote Implementation:**

```python
from beaver.client import BeaverClient
db = BeaverClient(base_url="http://127.0.0.1:8000")
```

All subsequent code, such as `db.dict("config")["theme"] = "dark"` or `db.collection("docs").search(...)`, remains identical.

### 4. Implementation Design: Remote Managers and HTTP Client

The implementation will live in a new `beaver/client.py` file and will not depend on any SQLite logic.

1.  **Core Component**: The `BeaverClient` class will manage a persistent HTTP session using the **`httpx`** library, which provides connection pooling and supports both synchronous and asynchronous operations.
2.  **Remote Managers**: For each existing manager (e.g., `DictManager`, `CollectionManager`), a corresponding `RemoteDictManager` or `RemoteCollectionManager` will be created. These classes will contain no database logic; their methods will simply construct and send the appropriate HTTP requests to the server endpoints.
3.  **WebSocket Handling**: For real-time features like `db.channel("my_channel").subscribe()` and `db.log("metrics").live()`, the remote managers will establish WebSocket connections to the server's streaming endpoints. This will require new `WebSocketSubscriber` and `WebSocketLiveIterator` classes that read from the network stream instead of a local queue.
4.  **Optional Dependency**: `httpx` and any necessary WebSocket libraries will be included as a new optional dependency, such as `pip install "beaver-db[client]"`.

### 5. Alignment with Philosophy

This feature strongly aligns with the library's guiding principles:

* **Simplicity and Pythonic API**: By maintaining perfect API parity, it ensures the remote client is just as intuitive and simple to use as the local database.
* **Developer Experience**: It provides a frictionless path for scaling applications, which is a major enhancement to the developer experience.
* **Minimal Dependencies**: By keeping the client and its dependencies optional, the core library remains lightweight and dependency-free.
# BeaverDB Feature Roadmap

This document contains a curated list of clever ideas and feature designs for the future development of `beaver-db`. The goal is to track innovative modalities that align with the library's core philosophy of being a simple, powerful, local-first database for AI prototyping.

## Feature: Comprehensive Async API with On-Demand Wrappers

### 1. Concept

A **Comprehensive Async API** will be introduced to allow seamless integration of `beaver-db` into modern `asyncio`-based applications. Instead of making the core library asynchronous, this feature will provide an elegant, on-demand way to get an async-compatible version of any core `beaver-db` object.

The core of the library will remain fully synchronous, respecting its design principle of a "Synchronous Core with Async Potential". The async functionality will be provided through thin, type-safe wrappers that run the blocking database calls in a background thread pool, ensuring the `asyncio` event loop is never blocked.

### 2. Use Cases

This feature is essential for developers using modern Python frameworks and for building highly concurrent applications:

  * **Modern Web Backends**: Natively integrate `beaver-db` with frameworks like FastAPI or Starlette without needing to manage a separate thread pool executor for database calls.
  * **High-Concurrency Tools**: Use `beaver-db` in applications that manage thousands of concurrent I/O operations (like websocket servers, scrapers, or chatbots) without sacrificing responsiveness.
  * **Ergonomic Developer Experience**: Allow developers working in an `async` codebase to use the familiar `await` syntax for all database operations, leading to cleaner and more consistent code.

### 3. Proposed API

The API is designed to be flexible and explicit, allowing the developer to "opt-in" to the async version of an object whenever needed.

  * `docs = db.collection("articles")`: The developer starts with the standard, synchronous object.
  * `async_docs = docs.as_async()`: A new `.as_async()` method on any synchronous wrapper (`CollectionWrapper`, `ListWrapper`, etc.) will return a parallel `Async` version of that object.
  * `await async_docs.index(my_doc)`: All methods on the `Async` wrapper are `async def` and must be awaited. The method names are identical to their synchronous counterparts, providing a clean and consistent API.
  * `await docs.as_async().search(vector)`: For one-off calls, the developer can chain the methods for a concise, non-blocking operation.

### 4. Implementation Design: Type-Safe Parallel Wrappers

The implementation will prioritize correctness, flexibility, and compatibility with developer tooling.

1.  **Parallel Class Hierarchy**: For each core wrapper (e.g., `CollectionWrapper`), there will be a corresponding `AsyncCollectionWrapper`. This new class will hold a reference to the original synchronous object.
2.  **Explicit `async def` Methods**: Every method on the `Async` wrapper will be explicitly defined with `async def`. This ensures that type checkers (like Mypy) and IDEs can correctly identify them as awaitable, preventing common runtime errors and providing proper autocompletion.
3.  **`asyncio.to_thread` Execution**: The implementation of each `async` method will simply call the corresponding synchronous method on the original object using `asyncio.to_thread`. This delegates the blocking I/O to a background thread, keeping the `asyncio` event loop free.

### 5. Alignment with Philosophy

This feature perfectly aligns with the library's guiding principles:

  * **Synchronous Core with Async Potential**: It adds a powerful `async` layer without altering the simple, robust, and synchronous foundation of the library.
  * **Simplicity and Pythonic API**: The `.as_async()` method is an intuitive and Pythonic way to opt into asynchronous behavior, and the chained-call syntax is elegant and clean.
  * **Developer Experience**: By ensuring the `async` wrappers are explicitly typed, the design prioritizes compatibility with modern developer tools, preventing bugs and improving productivity.

## Feature: Pydantic Model Integration for Type-Safe Operations

### 1. Concept

This feature will introduce optional, type-safe wrappers for `beaver-db`'s data structures, powered by Pydantic. By allowing developers to associate a Pydantic model with a dictionary, list, or queue, the library will provide automatic data validation, serialization, and deserialization. This enhances the developer experience by enabling static analysis and autocompletion in modern editors.

### 2. Use Cases

  * **Data Integrity**: Enforce a schema on your data at runtime, preventing corrupted or malformed data from being saved.
  * **Improved Developer Experience**: Get full autocompletion and type-checking in your IDE, reducing bugs and improving productivity.
  * **Automatic Serialization/Deserialization**: Seamlessly convert between Pydantic objects and JSON without boilerplate code.

### 3. Proposed API

The API is designed to be intuitive and "Pythonic", aligning with the existing design principles of the library.

```python
from pydantic import BaseModel
from beaver import BeaverDB

class Person(BaseModel):
    name: str
    age: int

db = BeaverDB("data.db")

# Dictionaries
users = db.dict("users", model=Person)
users["alice"] = Person(name="Alice", age=30)
alice = users["alice"] # Returns a Person object

# Lists
people = db.list("people", model=Person)
people.push(Person(name="Bob", age=40))
bob = people[0] # Returns a Person object

# Queues
tasks = db.queue("tasks", model=Person)
tasks.put(Person(name="Charlie", age=50), priority=1)
charlie_item = tasks.get()
charlie = charlie_item.data # Returns a Person object
```

### 4. Implementation Design: Generic Wrappers with Pydantic

The implementation will use Python's `typing.Generic` to create type-aware wrappers for the data structures.

  * **Generic Managers**: `DictManager`, `ListManager`, and `QueueManager` will be converted to generic classes (e.g., `ListManager(Generic[T])`).
  * **Serialization/Deserialization**: Internal `_serialize` and `_deserialize` methods will handle the conversion between Pydantic models and JSON strings.
  * **Optional Dependency**: `pydantic` will be an optional dependency, installable via `pip install "beaver-db[pydantic]"`, to keep the core library lightweight.

### 5. Alignment with Philosophy

This feature aligns with `beaver-db`'s guiding principles:

  * **Simplicity and Pythonic API**: The `model` parameter is a simple and intuitive way to enable type safety.
  * **Developer Experience**: This feature directly addresses the developer experience by providing type safety and editor support.
  * **Minimal & Cross-Platform Dependencies**: By making `pydantic` an optional dependency, the core library remains minimalistic.

## Feature: Drop-in REST API Client (`BeaverClient`)

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

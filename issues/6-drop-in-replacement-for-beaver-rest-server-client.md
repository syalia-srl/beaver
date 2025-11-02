---
number: 6
title: "Drop-in replacement for Beaver REST server client"
state: open
labels:
- enhancement
---

### 1. Feature Concept

This feature involves the full implementation of the `BeaverClient` and its associated `Remote...Manager` classes. The `BeaverClient` will act as a **drop-in, API-identical replacement** for the local `BeaverDB` class.

Instead of interacting with a local SQLite file, this client will execute all operations by making **HTTP and WebSocket requests** to a remote `beaver serve` instance. This allows a user to switch seamlessly from a local, embedded database to a client-server architecture simply by changing their `db` object's instantiation.

This feature is a cornerstone of the project's "Local-First & Embedded" but "Client-Server Mode" enabled philosophy.

### 2. Use Cases

  * **Seamless Scaling:** Effortlessly transition a project from a local prototype to a networked service without a code rewrite.
  * **Multi-Process/Machine Access:** Allow multiple processes or machines (e.g., a pool of web workers, microservices) to share and interact with a single, centralized BeaverDB instance.
  * **Language Interoperability Blueprint:** While this client will be in Python, its implementation provides a clear blueprint for creating clients in other languages to interact with the BeaverDB server.

### 3. API & Implementation Details

This feature will be implemented by filling out the skeleton methods in `beaver/client.py`.

#### A. Dependencies

1.  **`httpx`:** This will be the new core dependency for the client, used for all synchronous HTTP requests (GET, PUT, POST, DELETE).
2.  **`websockets`:** This dependency will be required for the real-time features (`.channel()` and `.log().live()`) as proposed in the issue.
3.  **`pyproject.toml`:** A new optional dependency group, `[client]`, will be created:
    ```toml
    [project.optional-dependencies]
    vector = ["faiss-cpu>=1.12.0"]
    server = ["fastapi[standard]>=0.118.0"]
    client = ["httpx", "websockets"] # <-- New Line
    full = ["beaver-db[server]", "beaver-db[vector]", "beaver-db[client]"] # <-- Updated Line
    ```

#### B. `BeaverClient` (Main Class)

  * `__init__(self, base_url, **httpx_args)`: Will instantiate and store `httpx.Client(base_url=base_url, **httpx_args)`.
  * `close(self)`: Will call `self._client.close()`.
  * The `dict()`, `list()`, `queue()`, etc., factory methods will be fully implemented to return the `Remote...Manager` instances (they are currently stubs).

#### C. `Remote...Manager` Implementation

All `Remote...Manager` classes will be filled out to map their Python methods to the corresponding REST API endpoints defined in `beaver/server.py`.

  * **`RemoteDictManager`:**

      * `__getitem__(self, key)`: Calls `GET /dicts/{name}/{key}`. Will check for a 404 response and raise `KeyError`.
      * `__setitem__(self, key, value)`: Calls `PUT /dicts/{name}/{key}` with a JSON body.
      * `__delitem__(self, key)`: Calls `DELETE /dicts/{name}/{key}`.
      * `__len__(self)`: Calls `GET /dicts/{name}/count` and returns the `count` from the JSON response.

  * **`RemoteQueueManager`:**

      * `put(self, data, priority)`: Calls `POST /queues/{name}/put` with JSON body `{"data": data, "priority": priority}`.
      * `get(self, block=True, timeout=5.0)`: Calls `DELETE /queues/{name}/get` with query parameters `?timeout={timeout}`. It will handle a 408 Timeout response by raising `TimeoutError`.

  * **`RemoteCollectionManager`:**

      * `index(self, document, ...)`: Will serialize the `Document` into the `IndexRequest` format and call `POST /collections/{name}/index`.
      * `search(self, vector, top_k)`: Will serialize the vector into the `SearchRequest` format and call `POST /collections/{name}/search`.

  * **`RemoteBlobManager`:**

      * `put(self, key, data, metadata)`: This is a special case. It will construct a `multipart/form-data` request to match the `put_blob` endpoint in `beaver/server.py`, sending `files={"data": data}` and `data={"metadata": json.dumps(metadata)}`.
      * `get(self, key)`: Calls `GET /blobs/{name}/{key}` and returns the raw `response.content` (bytes) and metadata.

#### D. Real-time Features (WebSockets)

This is the most complex part of the implementation.

  * **`RemoteChannelManager.subscribe()`:** This will return a `RemoteSubscriber` object.

      * The `RemoteSubscriber.listen()` method will be a generator that:
        1.  Uses the `websockets` library to `connect` to the `ws://.../channels/{name}/subscribe` endpoint.
        2.  Enters an `async for message in websocket:` loop.
        3.  `yield json.loads(message)`.
      * This will require a small internal `asyncio` event loop runner or be based on the async client.

  * **`RemoteLogManager.live()`:** This will return a `RemoteLiveIterator` that performs the same function as above, connecting to the `ws://.../logs/{name}/live` endpoint.

  * **Async Client (`AsyncBeaverClient`):** The `as_async()` method will be implemented to return an `AsyncBeaverClient` that uses `httpx.AsyncClient` and async-native `websockets` calls, fulfilling the stubs in `beaver/client.py` and the plan in **Issue #2**.

### 4. High-Level Roadmap

1.  **Phase 1: Dependencies**

      * Update `pyproject.toml` to add the new `[client]` optional dependency group with `httpx` and `websockets`. Update the `[full]` group to include `[client]`.

2.  **Phase 2: Implement Stateless Managers (HTTP)**

      * Fully implement all methods in `RemoteDictManager`, `RemoteListManager`, and `RemoteBlobManager`. These are simple, stateless HTTP CRUD operations that map directly to the API in `beaver/server.py`.

3.  **Phase 3: Implement Stateful Managers (HTTP)**

      * Fully implement all methods in `RemoteQueueManager` (handling the blocking `get` call and timeout logic).
      * Fully implement all methods in `RemoteCollectionManager` (handling serialization to the Pydantic models required by the server, like `IndexRequest` and `SearchRequest`).
      * Implement `RemoteLockManager` by mapping `acquire` and `release` to corresponding (yet-to-be-planned) API endpoints.

4.  **Phase 4: Implement Real-time Managers (WebSocket)**

      * Implement the WebSocket-based `RemoteChannelManager.subscribe()` and `RemoteSubscriber.listen()`.
      * Implement the WebSocket-based `RemoteLogManager.live()`.

5.  **Phase 5: Implement `AsyncBeaverClient`**

      * Implement the `AsyncBeaverClient` class using `httpx.AsyncClient`.
      * Create async-native versions of all `Remote...Manager` classes that are returned by the `AsyncBeaverClient`. This fulfills a large part of **Issue #2**.

6.  **Phase 6: Documentation**

      * Update the `README.md` and `docs/guide-deployment.qmd` to heavily feature the `BeaverClient` as the standard way to interact with a `beaver serve` instance.
---
number: 35
title: "Refactor Core to \"Shared Interface Definition\" (SID) Architecture"
state: open
labels:
---

## Context

Currently, the BeaverDB ecosystem suffers from code duplication and interface drift between the Core (`AsyncBeaverDB`), the Sync Facade (`BeaverDB`), the REST Server (`server.py`), and the Client (`client.py`). Adding a new feature requires manual updates in four different places. Furthermore, the remote client lacks type safety, and real-time features (streams) are difficult to expose consistently over HTTP.

## Goal

Implement the **Shared Interface Definition (SID)** strategy. This approach moves the API definition (HTTP verbs, paths, streaming behavior) directly onto the Core `AsyncBeaver*` classes using decorators. The Server and Client then dynamically generate their routes and methods by inspecting these definitions.

Additionally, we will introduce a formal Protocol hierarchy (`IAsyncBeaver*`) to ensure strict type safety across Local/Remote and Sync/Async usage, unified under a single `beaver.connect()` entry point.

## Architecture Design

### 1. The Unified `@api` Decorator

We will introduce a lightweight, declarative module `beaver/api.py` containing a single `@api` decorator. This decorator will be applied to methods in the Core `AsyncBeaver` classes to define their public interface.

**Features:**

- **Declarative:** Defines HTTP Method (`GET`, `POST`, etc.) and Path (`/{key}`).
- **Streaming Support:** A `stream=True` flag signals that the method returns an `AsyncIterator` and should be exposed via HTTP Streaming (NDJSON).
- **Parameter Injection:** Supports server-side dependency injection (e.g., aggregators, internal flags) which are **stripped** from the public API signature (OpenAPI/Client), ensuring security and simplicity.


**Example Usage (Conceptual):**

```python
# beaver/logs.py

@api("/live", method="GET", stream=True, aggregator=my_safe_aggregator)
async def live(self, window: int, aggregator=None):
    # 'aggregator' is injected server-side; Client only sees 'window'
    pass
```

### 2. Type-Safe Protocols (`beaver/interfaces.py`)

To solve the client type-safety issue, we will define the entire API surface area using Python `Protocol` classes in a new file `beaver/interfaces.py`.

**Hierarchy:**

- **`IAsyncBeaverDB`**: The main factory interface.
- **`IAsyncBeaver[Structure]`**: Generic protocols for each data structure (e.g., `IAsyncBeaverDict`, `IAsyncBeaverLog`).
- **`IBeaverDB` & `IBeaver[Structure]`**: Synchronous equivalents for the Facade.


**Impact:**

- `AsyncBeaverDB` (Local) will inherit from `IAsyncBeaverDB`.
- `AsyncBeaverClient` (Remote) will claim to return `IAsyncBeaverDB` types (via type hinting/casting), enabling full IDE autocomplete and type checking, even though it uses dynamic proxying internally.


### 3. Universal Entry Point

We will unify instantiation into a single smart function in `beaver/__init__.py`.

```python
def connect(source: str, sync: bool = False, **kwargs) -> IAsyncBeaverDB | IBeaverDB:
    ...
```

- **Source Detection:** Detects if `source` is a file path (Local) or a URL (Remote).

- **Sync/Async Toggle:**

    - If `sync=False`: Returns `AsyncBeaverDB` (Local) or `AsyncBeaverClient` (Remote).
    - If `sync=True`: Wraps the Async instance (Local or Remote) in the `BeaverDB` reactor thread/Bridge.


### 4. Dynamic Server Generation

The `beaver/server.py` module will be refactored to remove manual route definitions. Instead, it will:

1. Iterate over registered Manager classes (mapped to prefixes like `/dicts`, `/queues`).

2. Inspect methods for the `@api` decorator.

3. **Transplant Signatures:** Dynamically rewrite the function signature for FastAPI to:

    - Remove `self`.
    - Remove injected private parameters.
    - Add `resource_name` and `db` dependencies.

4. **Route Registration:** Automatically register standard HTTP routes or `StreamingResponse` (NDJSON) endpoints based on the `stream` flag.


### 5. Dynamic Client Proxy

The `beaver/client.py` module will leverage the SID metadata to generate requests on the fly.

- The client will inspect the _Core Class_ (e.g., `AsyncBeaverDict`) to find the `@api` decorator for a called method.
- It will construct the URL and Method based on the decorator.
- If `stream=True`, it will use `httpx.stream()` and yield lines (NDJSON).
- If `stream=False`, it will use standard `client.request()`.


## Implementation Plan

1. **Phase 1: Interfaces & API Definition**

    - Create `beaver/interfaces.py` with full Protocol hierarchy.
    - Create `beaver/api.py` with the `@api` decorator.

2. **Phase 2: Core Refactoring**

    - Update all `AsyncBeaver*` managers in `beaver/` to inherit from `IAsyncBeaver*`.
    - Apply `@api` decorators to all public methods in these managers.

3. **Phase 3: Server & Client Logic**

    - Refactor `server.py` to use `create_router_for_manager` logic (removing manual endpoints).
    - Refactor `client.py` to use `RemoteManager` dynamic proxy logic (removing manual implementations).

4. **Phase 4: Unification**

    - Implement `beaver.connect()` factory.
    - Update `BeaverDB` (Sync Facade) to accept a factory/awaitable instead of hardcoded instantiation.


## Success Criteria

- [ ] Adding a method to `AsyncBeaverDict` and decorating it immediately makes it available in the REST API and Python Client.
- [ ] `client.dict("cache").get("key")` has full IDE autocomplete support.
- [ ] `beaver.connect("http://localhost:8000")` works identically to `beaver.connect("./beaver.db")` (API parity).
- [ ] Streaming endpoints (logs/channels) work over HTTP via NDJSON.
- [ ] Internal parameters (like `aggregator` injection) are not visible in the public Swagger docs.
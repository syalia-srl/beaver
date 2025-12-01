---
number: 35
title: "Refactor Core to \\\"Shared Interface Definition\\\" (SID) Architecture"
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
---
number: 36
title: "Implement SID Consumers (Dynamic CLI, Universal Client & Server)"
state: open
labels:
---

## Context

We have established the **Shared Interface Definition (SID)** architecture in the Core, enabling `AsyncBeaver*` managers to define their API surface via standard Python protocols.

However, currently:

1.  **CLI is Manual:** Adding a new feature to the Core requires writing manual `typer` commands in `beaver/cli/`.
2.  **Client is Missing:** There is no remote client implementation that mirrors the local API.
3.  **Connectivity is Fragmented:** Users have to instantiate `BeaverDB` for local files but would need a different class for remote connections.

## Goal

Implement the "Dynamic Consumer" pattern where the CLI, Remote Client, and REST Server automatically generate their logic by introspecting the Core classes.

This will result in a **Zero-Maintenance** system where adding a method to `AsyncBeaverDict` (decorated with `@expose`) immediately makes it available via:

  * The Python Remote Client (`client.dict("...").get(...)`)
  * The REST API (`GET /dicts/.../get`)
  * The CLI (`beaver dict ... get`)

## Architecture Design

### 1. The `@expose` Metadata Layer (`beaver/api.py`)

A unified decorator that tags Core methods with metadata for both HTTP and CLI usage.

```python
@expose(
    path="/{key}",
    method="GET",
    cli_name="get",
    cli_help="Retrieve a value."
)
async def get(self, key: str): ...
```

### 2. Universal Entry Point (`beaver/__init__.py`)

A single `connect()` function that acts as the universal factory, detecting the source type and returning the appropriate interface.

```python
# Usage
db_local  = beaver.connect("./my.db", sync=True)
db_remote = beaver.connect("http://localhost:8000", sync=True, api_key="...")
```

### 3. Dynamic Remote Client (`beaver/client.py`)

An `AsyncBeaverClient` that implements `IAsyncBeaverDB`. It uses a **Dynamic Proxy** (`RemoteManager`) that introspects the local Core classes to build `httpx` requests on the fly, caching the generated request methods for performance.

### 4. Self-Discovering CLI (`beaver/cli/discovery.py`)

A `typer` app generator that:

1.  Iterates over all Manager classes.
2.  Finds `@expose`d methods.
3.  Dynamically creates CLI commands, copying the function signature (arguments, types) so `typer` can parse arguments and generate `--help` automatically.

## Implementation Plan

### Phase 1: Metadata & Core

  - [ ] Create `beaver/api.py` with `EndpointMeta` and `@expose`.
  - [ ] Update all `AsyncBeaver*` managers in `beaver/` to:
      - Inherit from `IAsyncBeaver*` interfaces.
      - Apply `@expose` to all public methods.

### Phase 2: Universal Client

  - [ ] Implement `beaver/client.py` with `RemoteManager` proxy logic.
  - [ ] Implement `AsyncBeaverClient` factory.
  - [ ] Update `BeaverDB` (Sync Facade) to support wrapping `AsyncBeaverClient`.
  - [ ] Implement `beaver.connect()` in `beaver/__init__.py`.

### Phase 3: Dynamic Server

  - [ ] Refactor `beaver/server.py` to remove manual routes.
  - [ ] Implement `create_router_for_manager(cls)` to generate FastAPI routes from `@expose`.

### Phase 4: Self-Discovering CLI

  - [ ] Implement `beaver/cli/discovery.py` to generate `typer` apps from Core classes.
  - [ ] Refactor `beaver/cli/main.py` to use `beaver.connect()` and register discovered apps.
  - [ ] Delete manual CLI files (`beaver/cli/dicts.py`, etc.).

## Success Criteria

  - [ ] **One-Touch Updates:** Adding a method to `AsyncBeaverList` makes it appear in the CLI and Remote Client without extra code.
  - [ ] **Universal Access:** `beaver.connect("http://...")` works identically to `beaver.connect("./file.db")`.
  - [ ] **Rich CLI:** The CLI automatically validates types (e.g. `int`) and pretty-prints outputs using `rich`.
  - [ ] **Type Safety:** `mypy` passes on the Client usage (via `cast` in factory methods).
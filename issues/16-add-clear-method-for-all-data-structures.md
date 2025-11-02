---
number: 16
title: Add `clear` method for all data structures
---

### 1. Feature Concept

This feature introduces a new public method, `.clear()`, to all primary data managers: `DictManager`, `ListManager`, `CollectionManager`, `LogManager`, `QueueManager`, and `BlobManager`. This provides a simple, standardized, and atomic way to remove all data items from a specific, named data structure without deleting the structure itself.

This functionality will be exposed through the core Python library, the CLI, and the REST API to provide a consistent administrative tool. This plan directly supports the goals outlined in **Issue #15 (Enhance CLI with admin commands)**.

### 2. Use Cases

* **Testing & Development:** Allows for rapid resetting of the database state between test runs without deleting and recreating the entire `.db` file.
* **Data Purging:** Provides a simple way to clear out old or temporary data, such as emptying a `LogManager`, a `QueueManager` after all tasks are processed, or a `DictManager` used as a cache.
* **Administrative Tasks:** Enables a system administrator to clear a specific collection or data store via the CLI or REST API without needing to write custom SQL scripts.

### 3. API & Implementation Details

#### Core Library (`.clear()` method)

A new public `.clear()` method will be added to each of the following data manager classes:

* `DictManager`
* `ListManager`
* `QueueManager`
* `LogManager`
* `BlobManager`
* `CollectionManager`

**Implementation Details:**

* For simple managers (`Dict`, `List`, `Queue`, `Log`, `Blob`), this method will execute a single, atomic `DELETE FROM ... WHERE ..._name = ?` SQL command within a transaction.
* For `CollectionManager`, the implementation will be more comprehensive, atomically deleting all associated data from *all* related tables (e.g., `beaver_collections`, `beaver_fts_index`, `beaver_trigrams`, `beaver_edges`, and all vector-related tables like `_beaver_ann_...`) and resetting the collection version.

#### Command-Line Interface (CLI)

Following the structure proposed in **Issue #14** and **#15**, a new `clear` command will be added to each data structure's subcommand.

**Proposed CLI Commands:**

* `beaver dict <name> clear`
* `beaver list <name> clear`
* `beaver queue <name> clear`
* `beaver log <name> clear`
* `beaver blob <name> clear`
* `beaver collection <name> clear`

These commands will call the corresponding `.clear()` method on the manager and print a success or error message.

#### REST API Server

Following the existing API design in `beaver/server.py`, a new `DELETE` endpoint will be added for the root of each data structure resource.

**Proposed REST Endpoints:**

* `DELETE /dicts/{name}`
* `DELETE /lists/{name}`
* `DELETE /queues/{name}`
* `DELETE /logs/{name}`
* `DELETE /blobs/{name}`
* `DELETE /collections/{name}`

Each endpoint will call the corresponding `.clear()` method and return a JSON response, such as `{"status": "cleared"}`.

### 4. High-Level Roadmap

1.  **Phase 1: Core Library Implementation**
    * Add the `.clear()` method to the simple managers: `DictManager`, `ListManager`, `QueueManager`, `LogManager`, and `BlobManager`.
    * Implement the more complex, multi-table `.clear()` method in `CollectionManager`.

2.  **Phase 2: CLI Integration**
    * Add the new `clear` command to each corresponding file in `beaver/cli/` (e.g., `dicts.py`, `lists.py`, etc.).
    * Ensure all commands provide user-friendly success/error feedback using `rich`.

3.  **Phase 3: REST API Integration**
    * Add the `DELETE /{resource}/{name}` endpoint for all six data managers to `beaver/server.py`.
    * Update API documentation (if any) to reflect the new endpoints.
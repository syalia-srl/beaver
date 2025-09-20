# BeaverDB Feature Roadmap

This document contains a curated list of clever ideas and feature designs for the future development of `beaver-db`. The goal is to track innovative modalities that align with the library's core philosophy of being a simple, powerful, local-first database for AI prototyping.

---

## Feature: High-Performance Fuzzy Search

### 1. Concept

A **High-Performance Fuzzy Search** is a new query capability that allows for fast, typo-tolerant searches on document metadata. It solves the common and difficult problem of matching queries against data that may contain spelling mistakes or slight variations, which is essential for applications that handle real-world, user-generated content.

This is not a vector search or a standard full-text search. It is a specialized lexical search that measures the **typographical similarity** (or "edit distance") between strings, making the application feel smarter and more forgiving.

### 2. Use Cases

This feature is a game-changer for AI applications that need to be robust to messy data:
* **Entity Resolution**: An AI agent could reliably find a person or company in its knowledge base (e.g., "John Smith") even if the user's query contains a typo (e.g., "Jon Smithh").
* **Flexible Tagging**: It allows for the retrieval of documents based on tags that are spelled slightly differently (e.g., finding `#datascience` from a `#datascince` query).
* **Forgiving User Input**: It makes chatbots and search interfaces more robust by gracefully handling common spelling mistakes in user queries that filter document metadata.

### 3. Proposed API

The API will be clean and explicit, separating the one-time indexing cost from the fast search operation.

* `collection.index(doc, fuzzy_fields=["name", "author.name"])`: The existing `index` method will be augmented with a `fuzzy_fields` parameter. When a document is indexed, any field listed here will have a fuzzy search index built for its content.
* `results = collection.fuzzy(on_field="name", like="Jhn Smith", max_distance=2)`: A new, dedicated `fuzzy()` method will perform the high-speed search, returning documents where the specified field is within a given Levenshtein distance of the query string.

### 4. Implementation Design: The Trigram Index

To achieve high performance, this feature will be built on a **trigram index**, which transforms the fuzzy search problem into a fast, indexed lookup.

1.  **Schema**: A new table, `_beaver_trigram_index`, will be created. It will store 3-character chunks (trigrams) of the text from the indexed fields, linking each trigram back to the document it came from. This table will have a standard database index for lightning-fast lookups.

2.  **Indexing**: When `index()` is called with `fuzzy_fields`, the content of those fields is broken down into a set of trigrams, which are then stored in the `_beaver_trigram_index` table.

3.  **Two-Stage Search**: The `fuzzy()` method will execute a fast, two-stage query:
    * **Candidate Selection (SQL)**: First, it generates trigrams from the user's query and uses the fast trigram index to find a small set of candidate documents that share some of those trigrams.
    * **Refinement (SQL Function)**: Second, it uses a custom Levenshtein function registered with SQLite to calculate the precise "typo distance" *only* on the small set of candidates. This entire operation happens natively within the database engine for maximum performance.

### 5. Alignment with Philosophy

This feature is a perfect embodiment of the `beaver-db` design principles:
* **Minimalism**: It provides a powerful, high-concept feature with zero new dependencies, instead leveraging the native, extensible power of SQLite.
* **Performance**: It is designed from the ground up to be fast, avoiding the performance pitfalls of naive, full-table scan implementations.
* **Simple and Pythonic API**: It abstracts away the complexity of trigram indexing and two-stage searching behind a clean, intuitive, and explicit API.

---

## Feature: High-Performance, Persistent ANN Index

### 1. Concept

A **High-Performance, Persistent Approximate Nearest Neighbor (ANN) Index** is a new vector search implementation designed to overcome the limitations of the current in-memory k-d tree. It will provide a truly dynamic and durable index that supports fast, incremental additions and instant startups without requiring a full rebuild.

This feature elevates the vector search capability from a prototype-level tool to a robust, production-ready one by using a state-of-the-art library like `faiss` and a professional, crash-safe architecture.

### 2. Use Cases

This feature is essential for any application where the vector dataset is not static:
* **Real-time RAG**: In a Retrieval-Augmented Generation system where new documents are constantly being added, this allows the knowledge base to grow without any downtime or slow re-indexing periods.
* **Long-running Applications**: For any application that runs for more than a single session, this ensures that the vector index is as persistent and reliable as the rest of the database.
* **Large-Scale Search**: For datasets with hundreds of thousands of vectors or more, this provides state-of-the-art search speed and accuracy that the current k-d tree cannot match, especially in high-dimensional spaces.

### 3. Implementation Design: The Hybrid Index

This feature will be built using a **hybrid, two-tiered index system** that is both fast and crash-safe, while adhering to the single-file principle.

1.  **Core Technology**: It will use a high-performance ANN library like `faiss` to build the indexes.

2.  **Hybrid Structure**:
    * **Base Index**: A large, highly optimized Faiss index containing the majority of the vectors. This index is serialized and stored as a **BLOB** inside a dedicated SQLite table (`_beaver_ann_indexes`), ensuring it is part of the single database file.
    * **Delta Index**: A small, in-memory Faiss index that holds all newly added vectors for near-instant write performance.

3.  **Crash-Safe Recovery (The "Pending Log")**:
    * A new table, `_beaver_ann_pending_log`, will store the `item_id` of every vector added to the in-memory `delta_index`.
    * During a "compaction" process, the vectors from the pending log are merged into a new base index. In a single atomic transaction, the new index is saved to the BLOB and the pending log is cleared.
    * On startup, the system performs an instantaneous check of this pending log. If it contains IDs (due to a previous crash), it reloads only those few vectors, ensuring **zero data loss and a fast startup**.

### 4. Alignment with Philosophy

This feature represents a significant evolution of the library while respecting its core principles:
* **Single-File Principle**: By storing the serialized index as a BLOB, the entire database, including the ANN index, remains a single, portable file.
* **Performance and Correctness**: It introduces a state-of-the-art ANN implementation and a robust, transactional process to guarantee data integrity and recoverability.
* **Minimal Dependencies**: While it introduces a major new dependency (`faiss-cpu`), it does so for a monumental performance gain that is central to the library's purpose, aligning with the "monumental improvement" clause in the design principles.

---

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
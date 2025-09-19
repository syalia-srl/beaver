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

## Feature: Persistent Priority Queue

### 1. Concept

A **Persistent Priority Queue** is a new low-level data structure that stores items along with a user-defined priority. Unlike a standard list or queue (which are strictly FIFO/LIFO), this modality guarantees that the item retrieved is always the one with the **highest priority**, regardless of when it was added.

This is a fundamental feature for any application that needs to manage tasks or events by importance. Its persistence ensures that if the application restarts, the exact order of all pending tasks is perfectly preserved.

### 2. Use Cases

This is a critical modality for building more sophisticated AI systems:
* **AI Agent Task Management**: An agent can manage a to-do list where tasks have different urgencies. A priority queue ensures the agent always works on the most important task first (e.g., a priority 1 "respond to user" task before a priority 10 "summarize news" task).
* **Resource Scheduling**: Efficiently manage access to a limited resource, like a GPU, by allowing high-priority inference jobs to be processed before lower-priority batch processing tasks.
* **Event-Driven Systems**: In a system processing a stream of events, a priority queue ensures that high-priority events (like a `payment_failed` event) are handled before low-priority ones (like a `log_telemetry` event).

### 3. Proposed API

The API is designed to be minimal and intuitive, providing only the essential methods for a priority queue.

* `queue = db.priority_queue("tasks")`: Creates or loads a persistent priority queue.
* `queue.put(data, priority)`: Adds an item to the queue with a specific priority (a lower number means higher priority).
* `item = queue.get()`: Atomically removes and returns the item with the highest priority. The returned item is a dataclass containing the `priority`, `timestamp`, and `data`.
* `len(queue)`: Returns the current number of items in the queue.

### 4. Implementation Design

The performance of this feature is derived directly from a specialized database index.

1.  **Schema**: A new table, `beaver_priority_queues`, will store the `queue_name`, a `priority` (REAL), a `timestamp` (REAL), and the `data` payload (TEXT).
2.  **Compound Index**: A powerful compound index on `(queue_name, priority ASC, timestamp ASC)` is the key to the design. This pre-sorts the data, allowing SQLite to jump directly to the highest-priority item for a given queue in O(1) time. The timestamp is used as a tie-breaker, ensuring that items with the same priority are processed in the order they were received (FIFO).

### 5. Alignment with Philosophy

This feature is a perfect fit for the `beaver-db` design philosophy:

* **Distinct Modality**: Its ordering is based on a user-defined priority, making it a fundamentally different and new tool compared to the existing `ListWrapper`.
* **SQLite-Native Performance**: It leverages the native power of a compound B-Tree index in SQLite to deliver high performance without any complex application-level logic.
* **Simple and Pythonic API**: It abstracts away the indexed database table behind a clean, simple, and explicit API that is natural for any Python developer to use.
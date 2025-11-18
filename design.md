# BeaverDB Design Document

- **Version**: 2.0
- **Status**: Active (Async-First Refactor)
- **Last Updated**: October 2025

## 1. Introduction & Vision

`beaver-db` is a local-first, embedded, multi-modal database for Python. Its primary motivation is to provide a simple, single-file solution for modern applications that need to handle complex data types like vectors, documents, graphs, and probabilistic sketches without the overhead of a database server.

The vision for `beaver-db` is to be the "Swiss Army Knife" for embedded data. It empowers developers to start quickly with a simple, synchronous API but provides a seamless path to scale to high-concurrency workloads and client-server architectures without changing their application logic.

## 2. Guiding Principles

* **Local-First & Embedded:** The default mode is a single SQLite file. This is the non-negotiable source of truth.
* **Async-First Core, Sync Bridge:** To handle high concurrency (locks, pub/sub), the core logic is asynchronous. A synchronous bridge ensures the user-facing API remains simple and familiar ("Synchronous facade, Asynchronous engine").
* **Standard SQLite Compatibility:** The `.db` file must always be a valid SQLite file queryable by standard tools.
* **Minimal & Optional Dependencies:** The core is lightweight (`aiosqlite`, `numpy`). Heavy features (HNSW, REST server) are optional extras.
* **Simplicity and Pythonic API:** We prefer intuitive Python contexts (`with db.batched()...`) over custom DSLs.
* **Convention over Configuration:** Advanced features (like vector index strategies) should auto-detect and configure themselves whenever possible.

## 3. Architecture & Core Components

`beaver-db` is architected as a set of high-level managers around an asynchronous SQLite core.

### 3.1. Core Engine (Async-First)

* **`AsyncBeaverDB` (The Engine):** The internal core implementation using `asyncio` and `aiosqlite`. It manages the event loop, connection pooling, and state coordination.
* **`BeaverDB` (The Facade):** The public, synchronous class. It spins up a background "Reactor Thread" running the async loop and bridges all method calls to it via `run_coroutine_threadsafe`. This provides thread safety and ease of use without blocking the main application.
* **Concurrency:** Uses `PRAGMA journal_mode=WAL` for process safety. Internal locks and pub/sub mechanisms are implemented using non-blocking `asyncio` primitives.

### 3.2. Client-Server Mode

* **REST API Server:** An optional FastAPI wrapper around `AsyncBeaverDB` that exposes all functionality over HTTP/WebSockets.
* **`BeaverClient`:** A drop-in replacement for `BeaverDB` that implements the exact same API but routes operations to a remote server via `httpx`.

### 3.3. Data Models & Features

#### Key-Value & Blobs (`DictManager`, `BlobManager`)
* **Storage:** Standard tables for keys and binary blobs.
* **Batching:** Optimized for high-throughput ingestion via the `.batched()` context manager.

#### Lists & Queues (`ListManager`, `QueueManager`)
* **Lists:** Persistent ordered lists with O(1) push/pop using floating-point ordering.
* **Queues:** Priority queues with blocking `.get()` support. In the async core, polling is handled efficiently without threads.

#### Real-Time Data (`ChannelManager`, `LogManager`)
* **Pub/Sub:** A high-efficiency messaging system. The async core allows thousands of concurrent subscribers with minimal resource overhead.
* **Logs:** Time-indexed storage with support for live, aggregated dashboards (`.live()`).

#### Probabilistic Sketches (`SketchManager`)
* **Concept:** A "Small Data" solution for "Big Data" problems (cardinality, membership).
* **Implementation:** A unified **`ApproximateSet`** object that packs a **HyperLogLog** and **Bloom Filter** into a single binary BLOB.
* **Zero-Dependency:** Implemented using standard library hashing and bitwise operations on arbitrary-precision integers.

### 3.4. Vector Search Engine (`CollectionManager`)

The collection system uses a **Swappable Strategy Pattern** to balance performance and complexity.

* **Hybrid Architecture:** All strategies use a "Base Snapshot + Delta Log" model to ensure crash safety and multi-process consistency.
    * **Writes:** Go to a fast, append-only log (`beaver_vector_change_log`).
    * **Reads:** Merge the on-disk Snapshot with the in-memory Log.
    * **Compaction:** Background process merges Log into Snapshot.
* **Strategies:**
    1.  **Linear (`NumpyVectorIndex`):** Default. Exact O(N) search. Zero extra dependencies. Good for <100k vectors.
    2.  **LSH (`LSHVectorIndex`):** Optional. Approximate O(k) search using Locality Sensitive Hashing. Fast, zero extra dependencies.
    3.  **HNSW (`HNSWVectorIndex`):** Optional. State-of-the-art O(log N) graph search using `hnswlib`. Requires `beaver-db[hnsw]`.

## 4. Roadmap

### Phase 1: The Async Refactor (Immediate Focus)
* Migrate core logic to `aiosqlite` and `asyncio`.
* Implement the `BeaverDB` synchronous bridge (Portal Pattern).
* Refactor locks and pub/sub to use `await asyncio.sleep()` instead of threads.

### Phase 2: High-Performance Features
* Implement **Swappable Vector Strategies** (Protocol definition, LSH, HNSW).
* Implement **Probabilistic Sketches** (`ApproximateSet`).
* Implement **Batched Operations API** (`.batched()`) for bulk I/O.

### Phase 3: Stability & Client Parity (Long Term)
* Achieve 100% API parity between `BeaverDB` (Local) and `BeaverClient` (Remote).
* Comprehensive concurrency testing suite.
* Performance benchmarking and optimization of the async bridge.

### Explicitly Out of Scope
* Replication or distributed consensus (Raft/Paxos).
* Multi-file sharding.
* Proprietary storage formats (must remain SQLite compatible).
---
number: 1
title: "Refactor vector store to use FAISS"
state: closed
labels:
---

# Feat: High-Performance, Persistent Vector Search

This pull request introduces a complete overhaul of the vector search functionality, evolving it from an in-memory prototype into a persistent, high-performance, and multi-process-safe system. This resolves the limitations of the previous scipy.cKDTree implementation and aligns with the project's goal of providing a robust, local-first database for AI applications.

## Summary of Changes

- Persistent ANN Index: Replaces the in-memory k-d tree with a faiss-based Approximate Nearest Neighbor (ANN) index that is serialized and stored directly in the SQLite database file, ensuring data survives restarts.
- Modular VectorIndex Class: All vector-related logic has been encapsulated into a new, dedicated beaver/vectors.py file. The CollectionManager now delegates to this class, making the codebase cleaner and more maintainable.
- Robust Multi-Process Support: The entire system is designed to be safe for concurrent reads and writes from multiple processes, using a combination of WAL mode, explicit transaction locking, and a smart synchronization mechanism.
- Non-Blocking Background Compaction: A new compact() method runs in a background thread to merge changes into the main index without blocking the application, ensuring high availability.
- New Dependency: Adds faiss-cpu to the project dependencies.

## Detailed Implementation

1. Hybrid Index Architecture

  The new system uses a hybrid, two-tiered index to balance write performance with read efficiency:  
  - Base Index: A large, optimized faiss index stored as a BLOB in the _beaver_ann_indexes table.
  - Delta Index: A small, in-memory faiss index for new vectors, allowing for instantaneous indexing without modifying the large base index.

2. Crash-Safe and Concurrent by Design

  To handle concurrent writes and ensure durability, the index uses a log-based approach:
  - Pending & Deletion Logs: New vector additions and deletions are recorded in _beaver_ann_pending_log and _beaver_ann_deletions_log tables. This makes write operations extremely fast and atomic.
  - Intelligent Synchronization: A process automatically detects when its in-memory view is stale and performs a fast "catch-up" sync by only loading the changes from the logs, rather than performing a full index reload.
  -- Robust Initialization: The initial database schema creation in core.py is now wrapped in an EXCLUSIVE transaction, preventing race conditions when multiple processes start simultaneously.

3. Automatic Background Compaction

  The CollectionManager now automatically triggers a non-blocking compact() operation in a background thread when the number of un-compacted changes exceeds a threshold (default: 1000).

  This process rebuilds the base index from the logs and atomically swaps it in, ensuring the index remains optimized over time without sacrificing application performance.

4. Singleton CollectionManager

  To ensure consistent state management of the VectorIndex across a single BeaverDB instance, db.collection() now returns a singleton instance, mirroring the proven pattern used by db.channel().

##How to Test

This PR includes two new example scripts to validate the new functionality:

- examples/stress_test.py: Indexes 1000 vectors to test performance and the automatic compaction trigger, then runs searches to verify correctness.
- examples/general_test.py: A concurrency test where many separate processes write to the same collection simultaneously to validate the locking and synchronization logic.
# Search Internals

The `CollectionManager` provides a unified search interface, but under the hood, it orchestrates three distinct query engines:
1.  **Vector Engine:** For semantic similarity (dense retrieval).
2.  **FTS Engine:** For keyword matching (sparse retrieval).
3.  **Graph Engine:** For structural traversal (relational retrieval).

This document details how each engine is implemented.

## Vector Engine (Hybrid Architecture)

The vector search implementation (`beaver.vectors.NumpyVectorIndex`) is designed to be **Crash-Safe**, **Persistent**, and **Fast**.

To achieve this without an external vector database, BeaverDB uses a **Hybrid Snapshot + Delta Log** architecture.

### The Challenge

* **Naive Approach:** Store vectors in SQLite rows. `SELECT` + compute distance in Python.
    * *Problem:* Too slow. Serialization overhead for 100k vectors is massive.
* **Memory Approach:** Load all vectors into a `numpy` matrix at startup.
    * *Problem:* Startup time is slow. Syncing writes across processes is hard.

### The Solution: Snapshot + Log

We maintain two structures:
1.  **Base Index (Snapshot):** A serialized, memory-mapped binary blob containing a pre-computed `numpy` matrix of vectors up to time $T$.
2.  **Delta Log (Append-Only):** A standard SQLite table (`beaver_vector_change_log`) recording every insertion and deletion since time $T$.

### The Lifecycle
1.  **Startup:**
    * The manager loads the Base Index (fast binary load).
    * It queries the Delta Log for changes *after* the snapshot's version.
    * It applies these changes to an in-memory "Delta Buffer".
2.  **Search (`O(N)`):**
    * The query vector is compared against the **Base Matrix** (using BLAS/SIMD).
    * The query vector is compared against the **Delta Buffer**.
    * Results are merged and sorted.
    * Deleted items (Tombstones) are filtered out.
3.  **Write:**
    * New vectors are simply `INSERT`ed into the Delta Log. This is atomic and fast.
4.  **Compaction:**
    * When the Delta Log grows too large (>100 items), a background thread merges the log into the Base Matrix and creates a new Snapshot.

## Text Search Engine (FTS5 + Trigrams)

BeaverDB provides robust text search using a two-layered approach.

### Layer 1: Exact & Boolean (FTS5)

We use SQLite's built-in **FTS5** virtual table (`beaver_fts_index`).
* **Tokenization:** Uses the `porter` stemmer (e.g., "running" -> "run").
* **Storage:** Maps `(collection, item_id)` to a bag-of-words index.
* **Querying:** Supports fast boolean logic (`python AND NOT java`).

### Layer 2: Fuzzy (Trigrams)

FTS5 fails on typos ("pytohn" won't match "python"). To solve this, we implement a **Trigram Index** (`beaver_trigrams`).
* **Ingestion:** The string "hello" is broken into `hel`, `ell`, `llo`.
* **Storage:** Rows in `beaver_trigrams` map these 3-char chunks to document IDs.
* **Retrieval:**
    1.  Break query "helo" -> `hel`, `elo`.
    2.  Find IDs that contain a high percentage of these trigrams (Candidate Generation).
    3.  Compute **Levenshtein Distance** on these candidates only (Verification).

## Graph Engine (Recursive CTEs)

The graph capabilities rely on the `beaver_edges` table, which stores directed, labeled edges.

To avoid the "N+1 Select Problem" (fetching a node, then fetching its neighbors in a loop), BeaverDB uses **SQL-Native Recursion**.

### Recursive Common Table Expressions (CTEs)

The `.walk()` and `.expand()` methods generate a single SQL query that executes the Breadth-First Search (BFS) entirely within the database engine.

```sql
WITH RECURSIVE bfs(item_id, current_depth) AS (
    -- 1. Start at the source node
    SELECT target_item_id, 1
    FROM beaver_edges
    WHERE source_item_id = ?

    UNION ALL

    -- 2. Recursively find neighbors
    SELECT edges.target_item_id, bfs.current_depth + 1
    FROM beaver_edges AS edges
    JOIN bfs ON edges.source_item_id = bfs.item_id
    WHERE bfs.current_depth < ?
)
SELECT DISTINCT item_id FROM bfs;
```

This approach allows retrieving thousands of connected nodes in milliseconds without round-tripping data to Python.

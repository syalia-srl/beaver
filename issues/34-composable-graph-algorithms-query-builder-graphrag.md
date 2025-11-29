---
number: 34
title: "Composable Graph Algorithms & Query Builder (GraphRAG)"
state: closed
labels:
- enhancement
- graph
- rag
- api
- performance
---

### 1. Concept

This feature transforms `CollectionManager` into a graph-native engine via a **Composable Query Interface**.

It introduces a `DocumentSet` class that acts as a lazy container for **Document IDs and Scores**.
* **Hybrid Execution:**
    * **Expansion:** Uses SQLite Recursive CTEs for fast, set-based traversal (BFS).
    * **Pathfinding:** Uses a "Harvest & Refine" strategy: SQL fetches the subgraph, pure Python (using `heapq`) runs Dijkstra.
* **Zero Dependencies:** All graph algorithms (PageRank, Dijkstra, K-Core) are implemented in pure Python.
* **Lazy Hydration:** Full `Document` objects are only fetched during iteration.

### 2. Use Cases

* **Reasoning Chains (Dijkstra):**

```python
  # Find the strongest connection between two concepts
  # Fetches relevant edges via SQL, runs Dijkstra in memory.
  trace = (
      docs.select("concept_A")
      .path(to="concept_B", max_hops=5)
  )
```

* **Weighted Expansion (Cost-Limited BFS):**

```python
# Expand until accumulated weight > 5.0
context = (
    docs.select("concept_A")
    .expand(max_cost=5.0)
)
```

### 3. Proposed API

#### A. Entry Points (`CollectionManager`)

  * **`.select(*seeds)`**: Returns a set from explicit IDs.
  * **`.near(vector, k=10)`**: Vector Search.
  * **`.match(query, k=10)`**: FTS/Fuzzy Search.

#### B. The `DocumentSet` Class

**Set Operations:**

  * **`.merge(other, mode="rrf")`**: Unions sets with rank fusion.
  * **`.where(field, value)`**: Exact metadata filtering.

**Graph Operations:**

  * **`.expand(hops=None, max_cost=None)`**:
      * **SQL-Native:** Uses Recursive CTE to traverse edges.
      * Adds discovered neighbors to the set.
  * **`.path(to=targets, max_hops=5)`**:
      * **Hybrid:** SQL CTE fetches the edge envelope (max\_hops); Python `heapq` runs Dijkstra to find the optimal weighted path.
      * Adds only the nodes on the shortest path.
  * **`.rank(algo="pagerank")`**:
      * **Hybrid:** SQL fetches induced subgraph; Python runs Power Iteration.
  * **`.prune(algo="k_core")`**:
      * **Hybrid:** SQL fetches degrees; Python runs Peeling.

### 4. Implementation Design

#### A. Schema (`beaver_edges`)

```sql
ALTER TABLE beaver_edges ADD COLUMN weight REAL DEFAULT 1.0;
```

#### B. SQL Engine (`expand`)

Uses Recursive CTEs for efficient bulk traversal (BFS).

```sql
WITH RECURSIVE bfs(item_id, current_cost) AS (
    SELECT item_id, 0.0 FROM seeds
    UNION ALL
    SELECT edges.target, bfs.current_cost + edges.weight
    FROM beaver_edges JOIN bfs ON ...
    WHERE bfs.current_cost + edges.weight <= ?
)
SELECT item_id FROM bfs;
```

#### C. Python Engine (`beaver.graphs`)

A zero-dependency module using standard library tools:

  * **`dijkstra`**: Uses `heapq` for weighted shortest path.
  * **`pagerank`**: Uses `numpy`
  * **`lpa`**: Uses `collections.Counter` for Label Propagation clustering.

### 5. Roadmap

1.  **Schema:** Add `weight` column to `beaver_edges`.
2.  **Refactor:** Rename `connect` -> `link`, add `unlink`.
3.  **Engine:** Implement `beaver/graphs.py` (Dijkstra, Rank, Cluster).
4.  **SQL:** Implement Recursive CTE for `.expand()`.
5.  **API:** Implement `DocumentSet` class.
6.  **Tests:** Verify Dijkstra finds correct weighted paths vs. simple BFS paths.
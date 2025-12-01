---
number: 24
title: "Refactor VectorIndex to be a swappable strategy and add Persistent LSH implementation"
state: open
labels:
---

## 1. Concept

The current `NumpyVectorIndex` provides a robust, zero-dependency default for vector search using a linear scan. However, its $O(N)$ complexity becomes a bottleneck as datasets grow beyond 10k-50k vectors.

This issue proposes a **"Hybrid Linear/LSH"** strategy that seamlessly transitions from exact search to approximate search based on dataset size, entirely powered by SQLite and NumPy.

### Key Features

1.  **Hybrid Strategy:** Automatically switches between **Linear Scan** (100% accurate, fast for small $N$) and **LSH** (Approximate $O(1)$, fast for large $N$).
2.  **Stateless & Persistent:** The index is stored in SQLite tables (`__beaver_lsh_index__`), not in memory. This ensures zero startup time and low memory footprint.
3.  **Metric Agnostic (via Normalization):** Optimizes for **Cosine Similarity** (the standard for AI embeddings) by normalizing vectors before hashing, allowing the use of SimHash (Random Projection).
4.  **Zero-Config:** No complex parameters for the user. We use mathematically optimal defaults (16-bit hashes, Hamming radius 1).

## 2. Justification

  * **Scalability:** Allows BeaverDB to handle millions of vectors without loading a massive HNSW graph into RAM.
  * **Simplicity:** By leveraging SQLite for the index structure, we avoid complex file management and concurrency issues inherent in external vector libraries.
  * **Consistency:** Updates are atomic. A vector and its LSH hash are committed in the same transaction, guaranteeing the index is always in sync.

## 3. Proposed API

The `AsyncBeaverVectors.near` method will be updated to support an explicit `method` parameter for benchmarking or forced accuracy, while defaulting to "auto".

```python
from typing import Literal

class AsyncBeaverVectors:
    async def near(
        self,
        vector: List[float],
        k: int = 10,
        method: Literal["auto", "exact", "lsh"] = "auto"
    ) -> List[VectorItem[T]]:
        """
        Finds the nearest k vectors.

        Args:
            vector: The query vector.
            k: Number of results to return.
            method: Search strategy.
                    - 'auto': Linear scan if N < 10k, else LSH. (Default)
                    - 'exact': Forces a linear scan (O(N)). 100% accurate.
                    - 'lsh': Forces the LSH index usage (O(1)).
        """
        # ...
```

## 4. Implementation Design

### A. Database Schema

We will add two internal tables to support the LSH index.

1.  **`__beaver_lsh_config__`**: Stores the random projection matrix for each collection.

      * `collection` (TEXT PK)
      * `hyperplanes` (BLOB): Serialized $16 \times D$ NumPy matrix (float32).

2.  **`__beaver_lsh_index__`**: Maps hash buckets to item IDs.

      * `collection` (TEXT)
      * `bucket_id` (INTEGER): The 16-bit hash integer.
      * `item_id` (TEXT)
      * **PK:** `(collection, bucket_id, item_id)` — Automatically creates a covering index for fast lookups.

### B. The LSH Algorithm (SimHash)

  * **Initialization:** Generate a random matrix $H$ of shape $(16, D)$. Apply **QR Decomposition** to ensure hyperplanes are orthogonal (improves bucket entropy).
  * **Hashing:**
    1.  Normalize vector $v$: $\hat{v} = v / \|v\|$.
    2.  Project: $p = H \cdot \hat{v}$.
    3.  Binarize: $bits = (p > 0)$.
    4.  Convert bit array to integer `bucket_id`.

### C. The Search Logic ("Auto" Mode)

1.  **Threshold Check:** If `count() < 10,000` (configurable), run **Linear Scan**.
      * *Reasoning:* For small $N$, the overhead of SQL lookups \> NumPy raw speed.
2.  **LSH Lookup:**
      * Compute query hash $h$.
      * **Multi-Probe:** Generate candidate buckets for Hamming Distance $\le 1$.
          * Candidates = $\{h\} \cup \{ h \oplus 2^i \mid i \in 0..15 \}$.
          * This results in exactly **17 buckets** to check.
      * **SQL Pushdown:**
        ```sql
        SELECT v.vector, v.item_id
        FROM __beaver_lsh_index__ idx
        JOIN __beaver_vectors__ v ON idx.item_id = v.item_id
        WHERE idx.collection = ? AND idx.bucket_id IN (?, ?, ...)
        ```
3.  **Re-ranking:**
      * Deserialize the fetched candidate vectors.
      * Compute exact Cosine Similarity in NumPy.
      * Return top $k$.

### D. Configuration Defaults

  * **`nbits = 16`**: Creates $2^{16} \approx 65k$ buckets. optimal for datasets between 10k and 5M vectors.
  * **`threshold = 10,000`**: The approximate crossover point where LSH becomes faster than linear scan on standard hardware.

## 5. Roadmap

1.  **Schema Migration:** Add SQL to create the new tables in `AsyncBeaverDB._create_all_tables`.
2.  **Refactor `AsyncBeaverVectors`:**
      * Implement `_ensure_lsh_hyperplanes()`.
      * Implement `_hash_vector()`.
      * Update `set()` to write to both tables transactionally.
      * Implement `_lsh_search()` and the new `near()` logic.
3.  **Benchmark Script:** Add `beaver/tuning.py` to verify the crossover point (Linear vs LSH) on the target machine.
4.  **Tests:** Add unit tests for `method="exact"` vs `method="lsh"` to ensure recall is acceptable (\>90% for standard distributions).
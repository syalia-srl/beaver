---
number: 30
title: "Add Probabilistic Sketches (Approximate Sets & Counters)"
state: open
labels:
---

### 1. Concept

This feature introduces a new data modality: **Probabilistic Data Structures (Sketches)**.

Sketches allow users to handle massive datasets (e.g., "Have I seen this URL?", "Count unique visitors") with a tiny, fixed memory footprint (e.g., 16KB). They trade perfect accuracy for extreme space efficiency.

To adhere to BeaverDB's "Simplicity" philosophy, we will implement a unified **`ApproximateSet`** structure that combines two best-in-class algorithms into a single, easy-to-use object:
1.  **Bloom Filter:** For probabilistic membership testing (`__contains__`).
2.  **HyperLogLog:** For cardinality estimation (`__len__`).

### 2. Use Cases

* **Deduplication:** Efficiently check if an item has been processed before (e.g., web crawler history) without storing the item itself.
* **Analytics:** Count millions of unique events (users, IP addresses, page views) with negligible storage cost.
* **Efficient Sets:** Maintain a set of 100 million items in ~100MB of space (vs. gigabytes for a standard `set` or B-Tree).

### 3. Proposed API

The API is exposed via a new `SketchManager`, accessed via `db.sketch()`. This factory method handles initialization, loading, and configuration validation in one step.

```python
# Initialize (or load) an Approximate Set
# We only ask for Bloom parameters; HLL configuration is fixed/standard (p=14).
visitors = db.sketch("daily_visitors", capacity=1_000_000, error_rate=0.01)

# High-Performance Write (Batched)
# Batching is REQUIRED for performance to avoid read-modify-write lock contention.
with visitors.batched() as batch:
    batch.add("192.168.1.1")
    batch.add("10.0.0.5")

# Membership Test (Bloom Filter)
if "192.168.1.1" in visitors:
    print("Seen this IP!")

# Cardinality Count (HyperLogLog)
print(f"Approximate unique count: {len(visitors)}")
```

### 4. Implementation Design

#### A. Schema (`beaver_sketches`)

Since sketches are fixed-size binary blobs, we store them as single rows.

```sql
CREATE TABLE IF NOT EXISTS beaver_sketches (
    name TEXT PRIMARY KEY,
    type TEXT NOT NULL, -- 'approx_set'
    config TEXT NOT NULL, -- JSON: {capacity, error_rate}
    data BLOB NOT NULL -- The packed binary state
);
```

#### B. The `ApproximateSet` Class

This class manages the in-memory state. It wraps two internal components implemented in pure Python/NumPy (Zero-Dependency):

  * **Storage:** A single `bytes` buffer.
      * **Offset 0-16KB:** HyperLogLog registers (Standard $p=14$ precision).
      * **Offset 16KB+:** Bloom Filter bit array (Size calculated from `capacity` & `error_rate`).
  * **Hashing:** Uses `hashlib.sha1` (HLL) and `hashlib.md5` + Double Hashing (Bloom) for stable, deterministic hashing across process restarts.

#### C. `SketchManager` & Batching

Because updating a BLOB is a Read-Modify-Write operation, strictly serializing every `.add()` via a lock would be too slow.

  * **Individual `.add()`:** Supported, but slow (acquires internal lock, reads BLOB, updates, writes BLOB).
  * **`.batched()`:** The primary interface.
    1.  Buffers items in memory.
    2.  Acquires lock **once**.
    3.  Reads BLOB.
    4.  Updates structure in memory (very fast bitwise ops).
    5.  Writes BLOB.
    6.  Releases lock.

#### D. Configuration Validation (Strict Mode)

To prevent data corruption, the `db.sketch()` factory enforces strict configuration matching on every call.

  * **On Call:** `db.sketch("name", capacity=C, error_rate=E)`
  * **Logic:**
    1.  Check if sketch `"name"` exists.
    2.  If yes, load its `config` from DB.
    3.  Compare stored `capacity` and `error_rate` with requested `C` and `E`.
    4.  **If mismatch:** Raise `ValueError`. *"Sketch 'name' exists with capacity=1M. Cannot load with requested capacity=500k."*
    5.  **If match (or defaults used):** Return the manager.

### 5. Roadmap

1.  Create `beaver/sketches.py` containing `BloomFilter`, `HyperLogLog`, and the unified `ApproximateSet` classes.
2.  Implement `SketchManager` in `beaver/sketches.py`.
3.  Implement `SketchBatch` for atomic bulk updates.
4.  Add `db.sketch()` factory method to `BeaverDB`, including the configuration validation logic.
5.  Add unit tests for accuracy (HLL error bounds) and persistence.
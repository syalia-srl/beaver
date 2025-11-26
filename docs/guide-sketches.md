# Sketches (Probabilistic Sets)

The `SketchManager` introduces a powerful "Big Data" capability to BeaverDB: **Probabilistic Data Structures**.

Unlike a standard `set` which stores every item you add (consuming more memory as it grows), a Sketch stores a **mathematical summary** of the data. It allows you to track the **Presence** and **Cardinality (Count)** of millions of items using a tiny, constant amount of memory (often just a few kilobytes).

The trade-off is that it provides *approximate* answers rather than perfect ones, but for many analytics and caching use cases, this is a perfect compromise.

## Quick Start

Initialize a sketch using `db.sketch()`. You define the expected **capacity** and acceptable **error rate**, and BeaverDB calculates the optimal storage size.

```python
from beaver import BeaverDB

db = BeaverDB("analytics.db")

# Create a sketch for tracking unique visitors
# Capacity: 1 million items
# Error Rate: 1% (0.01)
# Storage: ~1MB fixed size
visitors = db.sketch("daily_visitors", capacity=1_000_000, error_rate=0.01)

# 1. Add Data
visitors.add("192.168.1.1")
visitors.add("10.0.0.5")

# 2. Check Membership (Bloom Filter)
if "192.168.1.1" in visitors:
    print("Returning visitor")

# 3. Count Uniques (HyperLogLog)
print(f"Total unique visitors: {len(visitors)}")
```

## How It Works

BeaverDB implements a unified **`ApproximateSet`** that combines two best-in-class algorithms:

1.  **Bloom Filter:** Used for `__contains__` checks. It never gives false negatives (if it says "No", the item is definitely not there). It might give false positives (saying "Yes" when the item wasn't added) at the rate you configured (e.g., 1%).
2.  **HyperLogLog (HLL):** Used for `__len__` counts. It estimates the number of unique elements with a standard error of roughly 0.8% - 2%, regardless of how many billions of items you add.

These are packed into a single binary BLOB in the database, making them extremely efficient to load and save.

## Basic Operations

### Adding Items

Use `.add(item)` to insert a string or bytes. This updates both the Bloom Filter and the HLL counters.

```python
visitors.add("user_123")
```

### Membership Testing (Contains)

Use the `in` operator. This queries the Bloom Filter part of the sketch.

```python
# "Have we processed this URL before?"
if url in crawler_history:
    skip_url(url)
```

### Cardinality Estimation (Length)

Use `len()` to get the approximate count of unique items added. This queries the HyperLogLog part.

```python
# "How many distinct words are in this book?"
count = len(word_sketch)
```

## Advanced Features

### High-Performance Batching

Updating a sketch requires a Read-Modify-Write cycle on the BLOB. Doing this for every single item in a loop is slow due to locking overhead.

For high-throughput scenarios (like ingesting server logs), **always use `.batched()`**. This buffers updates in memory and performs a single atomic merge with the database.

```python
# Ingest 10,000 log entries efficiently
with visitors.batched() as batch:
    for ip in access_logs:
        batch.add(ip)
```

### Configuration Validation

BeaverDB enforces strict configuration matching. If you create a sketch with `capacity=1M` and later try to open it with `capacity=500k`, it will raise a `ValueError` to prevent data corruption.

```python
# Valid: Open with same parameters
v = db.sketch("visitors", capacity=1_000_000, error_rate=0.01)

# Invalid: Raises ValueError
v = db.sketch("visitors", capacity=500_000)
```

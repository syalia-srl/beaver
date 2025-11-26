# Lists

The `ListManager` provides a persistent, ordered collection of items that behaves like a standard Python `list`.

Unlike simpler key-value stores that might require rewriting a whole array to add an item, BeaverDB lists are implemented using **Fractional Indexing**. This allows for efficient `O(1)` insertions at the beginning, end, or *anywhere in the middle* of the list without shifting other elements.

## Quick Start

Initialize a list using `db.list()`.

```python
from beaver import BeaverDB

db = BeaverDB("app.db")
tasks = db.list("todo_list")

# 1. Add items
tasks.push("Buy milk")
tasks.prepend("Urgent: Fix bug")

# 2. Access items
print(tasks[0])  # -> "Urgent: Fix bug"
print(tasks[-1]) # -> "Buy milk"

# 3. Iterate
for task in tasks:
    print(f"- {task}")
```

## Basic Operations

### Adding Items

You can add items to the end, the beginning, or any specific position.

```python
# Add to the end (Append)
tasks.push("Walk the dog")

# Add to the beginning
tasks.prepend("Morning Meeting")

# Insert at a specific index
# This is efficient and does not require rewriting adjacent rows.
tasks.insert(1, "Check emails")
```

### Retrieving Items

Access items by their integer index. Negative indexing is supported.

```python
first = tasks[0]
last = tasks[-1]

# Slicing (Returns a generator/iterator to save memory)
# Note: This queries the DB range, it's very fast.
for item in tasks[1:3]:
    print(item)
```

### Removing Items

You can remove items by index (`pop`) or by value (`remove`).

```python
# Remove and return the last item
item = tasks.pop()

# Remove and return item at index 0
first_item = tasks.pop(0)

# Remove the first occurrence of a value
tasks.remove("Check emails")

# Clear the entire list
tasks.clear()
```

### Checking Existence & Length

Standard Python operators work as expected.

```python
if "Buy milk" in tasks:
    print("Don't forget the milk!")

print(f"Tasks remaining: {len(tasks)}")
```

## Advanced Features

### High-Performance Batching

When adding many items at once (e.g., importing logs or a feed), use `.batched()`. This is significantly faster than calling `.push()` in a loop because it calculates the order keys in memory and performs a single bulk insert.

> **Note:** The batch interface supports `.push()` and `.prepend()`. Arbitrary `.insert()` is not supported in batch mode to keep order calculation efficient.

```python
# Efficiently add 5,000 items
with tasks.batched() as batch:
    for i in range(5000):
        batch.push(f"Log entry {i}")
```

### Concurrency & Ordering

BeaverDB lists are process-safe.

  * **Order Stability:** Because items use floating-point keys for ordering, inserting an item between index 4 and 5 creates an item with order `4.5`. This means indices are stable; inserting at index 0 essentially "shifts" logical indices but doesn't require rewriting rows.

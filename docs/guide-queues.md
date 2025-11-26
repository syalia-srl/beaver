# Queues (Priority & Jobs)

The `QueueManager` provides a persistent, multi-process **Priority Queue**.

Unlike a standard list or FIFO queue, items in a BeaverDB queue are retrieved based on their **Priority Score**. This makes it ideal for building job queues, task schedulers, or message brokers where some tasks (like "send urgent email") must be processed before others (like "generate weekly report").

## Quick Start

Initialize a queue using `db.queue()`.

```python
from beaver import BeaverDB

db = BeaverDB("jobs.db")
queue = db.queue("email_jobs")

# 1. Producer: Add tasks with priority
# Priority 1.0 (High) comes before Priority 10.0 (Low)
queue.put({"to": "admin@example.com", "subject": "System Alert"}, priority=1.0)
queue.put({"to": "user@example.com", "subject": "Weekly Update"}, priority=10.0)

# 2. Consumer: Process tasks
# This blocks until an item is available
job = queue.get()

print(f"Processing: {job.data['subject']}")
# -> "System Alert" (because 1.0 < 10.0)
```

## Basic Operations

### Adding Items (Put)

Use `.put(data, priority)` to add an item.

  * **Data:** Any JSON-serializable object (dict, list, string, int).
  * **Priority:** A float. Lower numbers = Higher priority.
  * **FIFO Behavior:** Items with the *same* priority are retrieved in FIFO order (First-In, First-Out).

<!-- end list -->

```python
queue.put("Task A", priority=5)
queue.put("Task B", priority=5)
# Task A will be retrieved before Task B
```

### Retrieving Items (Get)

The `.get()` method is atomic and process-safe. It retrieves and **removes** the highest-priority item.

```python
# Blocking Get (Waits forever until item arrives)
item = queue.get()

# Non-Blocking Get (Raises IndexError if empty)
try:
    item = queue.get(block=False)
except IndexError:
    print("Queue is empty")

# Timeout (Waits 5 seconds, then raises TimeoutError)
try:
    item = queue.get(timeout=5.0)
except TimeoutError:
    print("No jobs arrived in 5 seconds")
```

### Peeking

Use `.peek()` to see the highest-priority item *without* removing it.

```python
next_job = queue.peek()
if next_job:
    print(f"Next up: {next_job.data}")
```

### Checking Size

```python
print(f"Pending jobs: {len(queue)}")
```

## Advanced Patterns

### Process-Safe Consumer Workers

You can run multiple Python scripts (workers) consuming from the same queue concurrently. BeaverDB uses SQLite locking to ensure that **each job is delivered to exactly one worker**.

```python
# worker.py
while True:
    try:
        # Wait for work
        job = queue.get()
        process(job.data)
    except Exception as e:
        print(f"Worker crashed: {e}")
```

### The `QueueItem` Object

When you retrieve an item, you get a `QueueItem` named tuple containing metadata:

  * **`data`**: The payload you stored.
  * **`priority`**: The float priority.
  * **`timestamp`**: When the item was added (used for FIFO tie-breaking).

<!-- end list -->

```python
item = queue.get()
print(f"Processing {item.data} (Priority: {item.priority}, Added at: {item.timestamp})")
```

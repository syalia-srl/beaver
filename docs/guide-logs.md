# Logs (Time-Series & Stream)

The `LogManager` is a specialized data structure for **Time-Series Data**. Unlike a dictionary (where keys are unique) or a list (ordered by insertion), a Log is ordered by **Timestamp**.

This is ideal for:

* **System Telemetry:** CPU usage, memory stats, sensor readings.
* **Audit Trails:** "User X changed setting Y at Time Z".
* **Chat History:** Storing messages chronologically.
* **Event Sourcing:** Storing a sequence of state-changing events.

## Quick Start

Initialize a log using `db.log()`.

```python
from beaver import BeaverDB
from datetime import datetime, timedelta

db = BeaverDB("telemetry.db")
metrics = db.log("server_metrics")

# 1. Log Events
# BeaverDB automatically records the current UTC timestamp.
metrics.log({"cpu": 12.5, "ram": 64})
metrics.log({"cpu": 45.0, "ram": 70})

# 2. Log with explicit timestamp
# You can backfill data by providing a datetime object.
yesterday = datetime.now() - timedelta(days=1)
metrics.log({"cpu": 10.0, "ram": 60}, timestamp=yesterday)

# 3. Iterate (Chronological Order)
for timestamp, data in metrics:
    print(f"[{timestamp}] CPU: {data['cpu']}%")
```

## Reading Data

### Time Range Queries

The most common operation on logs is fetching data for a specific window (e.g., "Show me errors from the last hour").

```python
now = datetime.now()
one_hour_ago = now - timedelta(hours=1)

# Efficiently queries the index for this range
recent_logs = metrics.range(start=one_hour_ago, end=now)

print(f"Found {len(recent_logs)} entries in the last hour.")
```

### Full Iteration

You can iterate over the entire history of the log.

```python
for ts, entry in metrics:
    process(entry)
```

## Real-Time Analysis (Live Views)

The "Killer Feature" of the LogManager is the `.live()` iterator. It allows you to build **Real-Time Dashboards** or **Monitoring Alerts** without writing complex polling loops or maintaining state.

It works by maintaining a **Rolling Window** over the most recent data and applying an **Aggregator Function** to it periodically.

### How it Works

1.  **Window:** "Look at the last 5 minutes of data."
2.  **Period:** "Update the result every 1 second."
3.  **Aggregator:** "Calculate the average CPU usage."

<!-- end list -->

```python
import statistics

# Define how to summarize the window
def calculate_avg_cpu(entries: list[dict]) -> float:
    if not entries:
        return 0.0
    values = [e["cpu"] for e in entries]
    return statistics.mean(values)

# Create the live view
# This returns an infinite iterator that blocks until the next period
live_view = metrics.live(
    window=timedelta(minutes=5),   # 5-minute rolling window
    period=timedelta(seconds=1),   # Yield a new result every second
    aggregator=calculate_avg_cpu
)

print("Starting Live Dashboard...")
for avg_cpu in live_view:
    print(f"Live CPU (5min avg): {avg_cpu:.2f}%")
    # This loop runs forever. Press Ctrl+C to stop.
```

### Async Support

For modern web applications (FastAPI, etc.), you can use the async version to stream updates via WebSockets/SSE.

```python
async_logs = db.log("metrics").as_async()

async for avg_cpu in async_logs.live(..., aggregator=calculate_avg_cpu):
    await websocket.send_json({"cpu": avg_cpu})
```

## Maintenance

### Batching

Just like other managers, use `.batched()` when ingesting high-frequency logs (e.g., 1000 requests/sec) to prevent database lock contention.

```python
# Ingest a batch of 1,000 sensor readings
with metrics.batched() as batch:
    for reading in sensor_stream:
        batch.log(reading)
```

### Clearing

To rotate logs or wipe history:

```python
metrics.clear()
```

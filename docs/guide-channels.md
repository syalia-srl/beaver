# Channels (Pub/Sub)

The `ChannelManager` provides a high-performance **Publish-Subscribe** messaging system.

Unlike Queues (where one item is processed by one worker), Channels implement a **Fan-Out** pattern: a message sent by one publisher is received by **all** active subscribers. This is perfect for event notifications, chat systems, or broadcasting updates to multiple services.

## Quick Start

Initialize a channel using `db.channel()`.

```python
import threading
from beaver import BeaverDB

db = BeaverDB("chat.db")
chat = db.channel("general_chat")

# 1. Subscriber (Listener)
# Runs in a background thread for this demo
def listen():
    # The 'with' block handles subscription cleanup automatically
    with chat.subscribe() as sub:
        print("Listening for messages...")
        # Blocks until a message arrives
        for message in sub.listen():
            print(f"Received: {message}")

t = threading.Thread(target=listen, daemon=True)
t.start()

# 2. Publisher (Sender)
# Messages are serialized to JSON and persisted to disk
chat.publish({"user": "alice", "text": "Hello World!"})
chat.publish({"user": "bob", "text": "Hi Alice!"})
```

## Basic Operations

### Publishing Messages

Use `.publish(payload)` to broadcast a message. The payload can be any JSON-serializable object (dict, list, string).

```python
# Broadcast a system event
db.channel("system").publish({
    "event": "maintenance_started",
    "duration_minutes": 60
})
```

### Subscribing

To receive messages, call `.subscribe()`. This returns a `Subscriber` object.
It is highly recommended to use it as a **Context Manager** (`with` statement) to ensure you strictly unsubscribe when done.

```python
channel = db.channel("system")

with channel.subscribe() as subscriber:
    # ... listen for messages ...
    pass
# Automatically unsubscribed here
```

### Listening

The `.listen()` method returns a blocking iterator. It yields messages as soon as they are written to the database.

```python
# Infinite loop (blocks forever)
for msg in subscriber.listen():
    process(msg)

# Timeout (blocks for N seconds, then stops if no message)
# Note: It raises queue.Empty or TimeoutError depending on implementation
try:
    for msg in subscriber.listen(timeout=5.0):
        print(msg)
except TimeoutError:
    print("No messages received.")
```

## Advanced Features

### Async Support

BeaverDB channels work seamlessly with `asyncio`. Use `.as_async()` to get an awaitable interface.

```python
import asyncio

async def watch_events():
    async_channel = db.channel("events").as_async()

    # Async Context Manager
    async with async_channel.subscribe() as sub:
        # Async Iterator
        async for message in sub.listen():
            print(f"Got event: {message}")
```

### Process Isolation

Channels are **Process-Safe**. You can have a publisher script running in one terminal and multiple subscriber scripts running in other terminals. They will all receive the messages in real-time via the shared SQLite file.

### Efficiency

BeaverDB uses a smart polling architecture. Regardless of how many subscribers you have in a single process (e.g., 100 WebSocket connections listening to a channel), BeaverDB runs only **one** background thread to poll the database. It then "fans out" the data to the 100 listeners in memory. This keeps CPU usage extremely low.

### History & Cleanup

Messages are persisted to the `beaver_pubsub_log` table. By default, new subscribers only see messages sent *after* they subscribed. To reclaim disk space, you can clear the channel history.

```python
# Delete all old messages for this channel
db.channel("general_chat").clear()
```

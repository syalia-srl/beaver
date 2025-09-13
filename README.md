# beaver 🦫

A single-file, multi-modal database for Python, built with the standard sqlite3 library.

`beaver` is the **B**ackend for **E**mbedded **A**synchronous **V**ector & **E**vent **R**etrieval. It's an industrious, all-in-one database designed to manage complex, modern data types without leaving the comfort of a single file.

This project is currently in its initial phase, with the core asynchronous pub/sub functionality fully implemented.

## Core Features (Current)

- **Zero Dependencies:** Built using only the standard Python `sqlite3` and `asyncio` libraries. No external packages to install.
- **Async Pub/Sub:** A fully asynchronous, Redis-like publish-subscribe system for real-time messaging between components of your application.
- **Single-File & Persistent:** All data is stored in a single SQLite file, making it incredibly portable and easy to back up. Your event log persists across application restarts.
- **Works with Existing Databases:** `beaver` can be pointed at an existing SQLite file and will create its tables without disturbing other data.

## Use Cases

I built `beaver` to have a local, embedded database for building small AI-powered projects without having to pay for a server-based database.

Examples include:

- Streaming messages and tokens from a local FastAPI to a local Streamlit app.
- Storing user files for Retrieval Augmented Generation in single-user applications.

## Installation

To use `beaver`, just run `pip install beaver-db` and import the main class.

```python
import asyncio
from beaver import BeaverDB


# --- Example Usage ---
async def listener(db: BeaverDB):
    """A sample task that listens for messages."""
    print("LISTENER: Waiting for messages on the 'system_events' channel...")
    try:
        async with db.subscribe("system_events") as subscriber:
            async for message in subscriber:
                print(f"LISTENER: Received -> {message}")
    except asyncio.CancelledError:
        print("LISTENER: Shutting down.")


async def publisher(db: BeaverDB):
    """A sample task that publishes messages."""
    print("PUBLISHER: Ready to send events.")
    await asyncio.sleep(1) # Give the listener a moment to start

    print("PUBLISHER: Sending user login event.")
    await db.publish(
        "system_events",
        {"event": "user_login", "username": "alice", "status": "success"}
    )

    await asyncio.sleep(2)

    print("PUBLISHER: Sending system alert.")
    await db.publish(
        "system_events",
        {"event": "system_alert", "level": "warning", "detail": "CPU usage at 85%"}
    )
    await asyncio.sleep(1)


async def main():
    """Runs the listener and publisher concurrently."""
    db = BeaverDB("demo.db")

    # Run both tasks and wait for them to complete
    listener_task = asyncio.create_task(listener(db))
    publisher_task = asyncio.create_task(publisher(db))

    await asyncio.sleep(5) # Let them run for a bit
    listener_task.cancel() # Cleanly shut down the listener
    await asyncio.gather(listener_task, publisher_task, return_exceptions=True)
    print("\nDemo finished.")


if __name__ == "__main__":
    # To run this demo, save the file as beaver.py and run `python beaver.py`
    print("--- BeaverDB Pub/Sub Demo ---")
    asyncio.run(main())
```

## Roadmap

`beaver` aims to be a complete, self-contained data toolkit for modern Python applications. The following features are planned for future releases, all accessible through a high-level API while still allowing direct SQL access:

- **Vector Storage & Search:** Store numpy vector embeddings alongside your data and perform efficient k-nearest neighbor (k-NN) searches.
- **Persistent Key-Value Store:** A simple get/set interface for storing configuration, session data, or any other JSON-serializable object.
- **JSON Document Store with Full-Text Search:** Store flexible JSON documents and get powerful full-text search across all text fields by default, powered by SQLite's FTS5 extension.
- **Standard Relational Interface:** While beaver provides high-level features, you will always be able to use the underlying SQLite connection for normal relational tasks, such as creating and managing users or products tables with standard SQL.

## Performance

Despite its local, embedded nature, `beaver` is highly performant by small use cases. Here are some metrics, measured on a single laptop, Intel Core i7, 7th generation.

- Process 100,000 messages (1000 messages times 100 asynchronous clients) in less than 30 seconds, giving over 3K messages per second with an average latency of only 100 ms (time elapsed between message generation and client processing).

## Why Beaver?

Beavers are nature's engineers. They build a single, robust, and complex home—the lodge—from many different materials.

Similarly, beaver builds a powerful, multi-modal database but contains it all within a single, self-contained file. It's an industrious, no-nonsense tool for building modern applications.

## License

This project is licensed under the MIT License.
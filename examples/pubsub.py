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

import asyncio
from beaver import BeaverDB

async def listener_task(name: str, db: BeaverDB):
    """An async task that listens for messages on a channel."""
    print(f"[{name}] Starting and subscribing to 'async_events'.")
    async_channel = db.channel("async_events").as_async()

    async with async_channel.subscribe() as listener:
        async for message in listener.listen():
            print(f"[{name}] Received -> {message}")

async def publisher_task(db: BeaverDB):
    """An async task that publishes several messages."""
    print("[Publisher] Starting.")
    async_channel = db.channel("async_events").as_async()

    await asyncio.sleep(1)
    print("[Publisher] Publishing message 1: User Login")
    await async_channel.publish({"event": "user_login", "user": "alice"})

    await asyncio.sleep(0.5)
    print("[Publisher] Publishing message 2: System Alert")
    await async_channel.publish({"event": "alert", "level": "high"})

    print("[Publisher] Finished publishing.")

async def main():
    """Sets up and runs the concurrent async publisher and listeners."""
    db = BeaverDB("async_demo.db")

    # Create and run the listener and publisher tasks concurrently
    listener_a = asyncio.create_task(listener_task("Listener-A", db))
    listener_b = asyncio.create_task(listener_task("Listener-B", db))
    publisher = asyncio.create_task(publisher_task(db))

    await publisher
    await asyncio.sleep(2) # Wait for messages to be processed

    # In a real app, you might cancel the listeners or have a shutdown event
    listener_a.cancel()
    listener_b.cancel()
    db.close()

if __name__ == "__main__":
    print("--- BeaverDB Async Pub/Sub Demo ---")
    asyncio.run(main())
    print("\nDemo finished successfully.")

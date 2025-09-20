import threading
import time
from beaver import BeaverDB

# --- 1. Listener Task ---
# This function will be run by each listener thread.
def listener_task(name: str, db: BeaverDB):
    """A task that listens for messages on a channel until shutdown."""
    print(f"[{name}] Starting and subscribing to 'system_events'.")

    # Get the singleton channel instance.
    channel = db.channel("system_events")

    # The 'with' statement handles registration and unregistration automatically.
    with channel.subscribe() as listener:
        # The .listen() method is a blocking iterator. It will yield messages
        # until the channel is shut down, at which point it will stop.
        for message in listener.listen():
            print(f"[{name}] Received -> {message}")

    print(f"[{name}] Finished and unsubscribed.")


# --- 2. Publisher Task ---
# This function will be run by the publisher thread.
def publisher_task(db: BeaverDB):
    """A task that waits a moment and then publishes several messages."""
    print("[Publisher] Starting.")

    # Get the same singleton channel instance.
    channel = db.channel("system_events")

    # Wait a moment to ensure listeners are subscribed and ready.
    time.sleep(1)

    print("[Publisher] Publishing message 1: User Login")
    channel.publish({"event": "user_login", "user": "alice"})
    time.sleep(0.5)

    print("[Publisher] Publishing message 2: System Alert")
    channel.publish({"event": "alert", "level": "high"})

    print("[Publisher] Finished publishing.")


# --- 3. Main Execution Block ---
def main():
    """Sets up and runs the concurrent publisher and listeners."""
    db = BeaverDB("demo.db")

    # Create threads for two listeners and one publisher.
    # The listeners will run until the db.close() call shuts them down.
    listener_a = threading.Thread(target=listener_task, args=("Listener-A", db))
    listener_b = threading.Thread(target=listener_task, args=("Listener-B", db))
    publisher = threading.Thread(target=publisher_task, args=(db,))

    # Start all threads.
    listener_a.start()
    listener_b.start()
    publisher.start()

    # Wait for the publisher to finish sending its messages.
    publisher.join()

    # In a real application, listeners might run for a long time.
    # Here, we'll wait a moment to ensure messages are processed before shutdown.
    print("\n[Main] Publisher finished. Waiting 2 seconds before shutdown...")
    time.sleep(2)

    # Gracefully close the database connection. This will signal all channel
    # polling threads to stop, which in turn causes the listener loops to exit.
    print("[Main] Closing database connection and shutting down listeners...")
    db.close()

    # Wait for the listener threads to complete their execution.
    listener_a.join()
    listener_b.join()

    print("\nDemo finished successfully.")


if __name__ == "__main__":
    print("--- BeaverDB High-Efficiency Pub/Sub Demo ---")
    main()

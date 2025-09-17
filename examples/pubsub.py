import threading
import time
from beaver import BeaverDB


def listener(db: BeaverDB):
    """A sample task that listens for messages in a blocking manner."""
    print("LISTENER: Waiting for messages on the 'system_events' channel...")

    # The subscriber is now a blocking iterator. This loop will pause
    # until a new message arrives.
    for message in db.subscribe("system_events"):
        print(f"LISTENER: Received -> {message}")
        # Add a condition to gracefully shut down the listener thread
        if message.get("event") == "shutdown":
            break

    print("LISTENER: Shutting down.")


def publisher(db: BeaverDB):
    """A sample task that publishes messages."""
    print("PUBLISHER: Ready to send events.")
    time.sleep(1)  # Give the listener a moment to start

    print("PUBLISHER: Sending user login event.")
    db.publish(
        "system_events",
        {"event": "user_login", "username": "alice", "status": "success"},
    )

    time.sleep(2)

    print("PUBLISHER: Sending system alert.")
    db.publish(
        "system_events",
        {"event": "system_alert", "level": "warning", "detail": "CPU usage at 85%"},
    )
    time.sleep(1)

    # Send a final message to tell the listener to stop
    print("PUBLISHER: Sending shutdown signal.")
    db.publish("system_events", {"event": "shutdown"})


def main():
    """Runs the listener and publisher concurrently using threads."""
    db = BeaverDB("demo.db")

    # Create separate threads for the listener and publisher
    listener_thread = threading.Thread(target=listener, args=(db,))
    publisher_thread = threading.Thread(target=publisher, args=(db,))

    # Start the threads
    listener_thread.start()
    publisher_thread.start()

    # Wait for both threads to complete their execution
    listener_thread.join()
    publisher_thread.join()

    print("\nDemo finished.")


if __name__ == "__main__":
    print("--- BeaverDB Synchronous Pub/Sub Demo ---")
    main()

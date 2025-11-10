import time
import random
from beaver import BeaverDB


def main():
    """
    Continuously publishes messages to a channel until manually stopped.
    """
    print("--- Starting Publisher Process ---")
    print("Publishing to 'live_events' channel. Press Ctrl+C to stop.")

    db = BeaverDB("demo.db")
    channel = db.channel("live_events")
    message_count = 0

    try:
        while True:
            # Construct a new message
            message_count += 1
            payload = {
                "message_id": message_count,
                "type": random.choice(["INFO", "WARNING", "ERROR"]),
                "timestamp": time.time(),
            }

            # Publish the message
            channel.publish(payload)
            print(f"Published: {payload}")

            # Wait for a random interval before sending the next one
            sleep_duration = random.uniform(1, 3)
            time.sleep(sleep_duration)

    except KeyboardInterrupt:
        print("\nPublisher shutting down...")
    finally:
        # Ensure the database connection is closed gracefully
        db.close()
        print("Publisher stopped.")


if __name__ == "__main__":
    main()

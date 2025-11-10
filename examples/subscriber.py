import queue
from beaver import BeaverDB


def main():
    """
    Continuously listens for messages on a channel until manually stopped.
    """
    print("--- Starting Subscriber Process ---")
    print("Listening to 'live_events' channel. Press Ctrl+C to stop.")

    db = BeaverDB("demo.db")
    channel = db.channel("live_events")

    try:
        # The 'with' block handles the subscription lifecycle.
        with channel.subscribe() as listener:
            # The listen() method with a timeout will raise queue.Empty
            # if no message is received within the specified time.
            for message in listener.listen(timeout=5):
                print(f"Received -> {message}")

            print("LOOP BREAK")

    except TimeoutError:
        print("\nNo message left...")
    except KeyboardInterrupt:
        print("\nManually stopped...")
    finally:
        # Ensure the database connection is closed gracefully.
        db.close()


if __name__ == "__main__":
    main()

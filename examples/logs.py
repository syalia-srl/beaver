import os
import random
import statistics
import threading
import time
from datetime import datetime, timedelta

from beaver import BeaverDB


def logging_worker(db: BeaverDB, stop_event: threading.Event):
    """A thread that writes random log data at a high frequency."""
    print("[Logger Thread] Starting to write logs...")
    logs = db.log("system_metrics")

    while not stop_event.is_set():
        # Log a new data point with a random value
        log_data = {"value": random.uniform(10, 100)}
        logs.log(log_data)

        # Aim for roughly 10 logs per second
        time.sleep(0.1)

    print("[Logger Thread] Stopped.")


def aggregate_metrics(window: list[dict]) -> dict:
    """
    An aggregator function that calculates statistics from a window of log data.
    """
    if not window:
        return {
            "count": 0,
            "mean": 0.0,
            "max": 0.0,
            "min": 0.0,
        }

    # Extract the 'value' from each log entry
    values = [log_entry.get("value", 0) for log_entry in window]

    return {
        "count": len(values),
        "mean": statistics.mean(values),
        "max": max(values),
        "min": min(values),
    }


def main():
    """
    Sets up a logging thread and a main thread to display a live,
    aggregated view of the log data.
    """
    db = BeaverDB("live_log_demo.db")
    logs = db.log("system_metrics")

    stop_event = threading.Event()

    # Start the background thread to write logs
    writer_thread = threading.Thread(
        target=logging_worker, args=(db, stop_event), daemon=True
    )
    writer_thread.start()

    # Give the writer a moment to start populating the log
    time.sleep(1)

    try:
        # Get the live iterator.
        # It will monitor a 5-second rolling window of data.
        # It will update and yield a new summary every 1 second.
        live_summary = logs.live(
            window=timedelta(seconds=5),
            period=timedelta(seconds=1),
            aggregator=aggregate_metrics,
        )

        print("[Main Thread] Starting live view. Press Ctrl+C to stop.")

        for summary in live_summary:
            # Clear the console for a clean, live view
            os.system("cls" if os.name == "nt" else "clear")

            print("--- Live Log Summary (5-second window) ---")
            print(f"Time: {datetime.now().strftime('%H:%M:%S')}")
            print("-" * 40)
            print(f"Log Count:  {summary['count']}")
            print(f"Mean Value: {summary['mean']:.2f}")
            print(f"Max Value:  {summary['max']:.2f}")
            print(f"Min Value:  {summary['min']:.2f}")
            print("\nPress Ctrl+C to stop.")

    except KeyboardInterrupt:
        print("\n[Main Thread] Shutdown signal received.")
    finally:
        # Gracefully stop the logging thread and close the database
        stop_event.set()
        writer_thread.join()
        db.close()
        print("[Main Thread] Application shut down gracefully.")


if __name__ == "__main__":
    main()

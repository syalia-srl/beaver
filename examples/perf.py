import asyncio
import os
import statistics
import time
from typing import List

# Ensure beaver.py is in the same directory or installed
from beaver import BeaverDB

# --- Test Configuration ---
DB_PATH = "performance_test.db"
TEST_CHANNEL = "benchmark_channel"
NUM_SUBSCRIBERS = 100
NUM_MESSAGES = 1000

# This list will be shared across all tasks to collect latency results
# It's safe to use a simple list because asyncio is single-threaded
all_latencies: List[float] = []


async def subscriber_task(subscriber_id: int, start_event: asyncio.Event):
    """
    Represents a single client subscribed to the channel.
    """
    db = BeaverDB(DB_PATH)

    # Subscribe and wait for the "START" signal from the publisher
    async with db.subscribe(TEST_CHANNEL) as subscriber:
        # Signal that this subscriber is ready
        start_event.set()

        messages_received = 0
        async for message in subscriber:
            if message.get("type") == "DATA":
                latency = time.perf_counter() - message["timestamp"]
                all_latencies.append(latency)
                messages_received += 1

            # Stop when the expected number of messages is received
            if messages_received >= NUM_MESSAGES:
                break


async def publisher_task(num_subscribers_ready: asyncio.Event):
    """
    Waits for subscribers to be ready, then publishes a burst of messages.
    """
    db = BeaverDB(DB_PATH)

    print(f"PUBLISHER: Waiting for {NUM_SUBSCRIBERS} subscribers to be ready...")
    await num_subscribers_ready.wait()
    await asyncio.sleep(0.5) # A brief pause to ensure all subscribers are listening

    print("PUBLISHER: All subscribers ready. Starting message burst...")

    start_time = time.perf_counter()

    for i in range(NUM_MESSAGES):
        await db.publish(
            TEST_CHANNEL,
            {"type": "DATA", "message_id": i, "timestamp": time.perf_counter()}
        )

    end_time = time.perf_counter()
    duration = end_time - start_time
    print(f"PUBLISHER: Finished publishing {NUM_MESSAGES} messages in {duration:.4f} seconds.")
    return duration


async def main():
    """
    Sets up the test, runs the subscribers and publisher, and reports results.
    """
    # Clean up previous database file if it exists
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    print("--- BeaverDB Pub/Sub Performance Test ---")
    print(f"Simulating {NUM_SUBSCRIBERS} subscribers and {NUM_MESSAGES} messages.")

    # An event to signal when a subscriber is ready
    subscriber_ready_event = asyncio.Event()

    # Create all subscriber tasks
    subscriber_tasks = [
        asyncio.create_task(subscriber_task(i, subscriber_ready_event))
        for i in range(NUM_SUBSCRIBERS)
    ]

    # Create the publisher task
    pub_task = asyncio.create_task(publisher_task(subscriber_ready_event))

    # Wait for the publisher to finish sending all its messages
    await pub_task

    # Now, wait for all subscribers to finish receiving all messages
    await asyncio.gather(*subscriber_tasks)

    print("\n--- Test Complete ---")

    # --- Reporting ---
    total_messages_received = len(all_latencies)
    expected_messages = NUM_SUBSCRIBERS * NUM_MESSAGES

    print(f"Total messages received: {total_messages_received} (Expected: {expected_messages})")

    if all_latencies:
        avg_latency = statistics.mean(all_latencies)
        median_latency = statistics.median(all_latencies)
        max_latency = max(all_latencies)
        min_latency = min(all_latencies)

        # Calculate total time from the first message sent to the last received
        total_duration = max_latency + (NUM_MESSAGES / (NUM_MESSAGES / (pub_task.result() if pub_task.done() else 0.001)))
        throughput = total_messages_received / total_duration if total_duration > 0 else 0


        print("\n--- Results ---")
        print(f"Average Latency: {avg_latency * 1000:.4f} ms")
        print(f"Median Latency:  {median_latency * 1000:.4f} ms")
        print(f"Min Latency:     {min_latency * 1000:.4f} ms")
        print(f"Max Latency:     {max_latency * 1000:.4f} ms")
        print(f"Total Throughput: {throughput:,.2f} messages/sec")


if __name__ == "__main__":
    asyncio.run(main())

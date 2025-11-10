import sys
import os
import random
import time
import uuid

from beaver import BeaverDB

DB_PATH = "tasks.db"
QUEUE_NAME = "distributed_task_queue"


def producer():
    """
    Runs in a loop, producing new tasks with random priorities and adding
    them to the shared queue.
    """
    pid = os.getpid()
    db = BeaverDB(DB_PATH)
    task_queue = db.queue(QUEUE_NAME)
    print(f"--- Starting Producer (PID: {pid}) ---")
    print("Producing tasks... Press Ctrl+C to stop.")

    try:
        while True:
            # 1. Create a new task with a unique ID
            task_id = str(uuid.uuid4())[:8]
            task_data = {"task_id": task_id, "created_by": pid}

            # 2. Assign a random priority (1=high, 10=low)
            priority = random.randint(1, 10)

            # 3. Put the task onto the queue
            task_queue.put(task_data, priority=priority)
            print(f"[{pid}] Produced task '{task_id}' with priority {priority}.")

            # 4. Wait for a random interval before producing the next task
            sleep_duration = random.uniform(0.5, 3.0)
            time.sleep(sleep_duration)

    except KeyboardInterrupt:
        print(f"\n--- Producer (PID: {pid}) stopping. ---")


def consumer():
    """
    Runs in a loop, consuming tasks from the shared queue. It will block
    and wait if the queue is empty.
    """
    pid = os.getpid()
    db = BeaverDB(DB_PATH)
    task_queue = db.queue(QUEUE_NAME)
    print(f"--- Starting Consumer (PID: {pid}) ---")
    print("Waiting for tasks... Press Ctrl+C to stop.")

    try:
        while True:
            try:
                # 1. Block and wait for a task for up to 5 seconds
                print(f"[{pid}] Waiting for a task (timeout=5s)...")
                item = task_queue.get(timeout=5.0)

                # 2. "Process" the task
                print(
                    f"[{pid}] Got task '{item.data['task_id']}' with priority {item.priority}. Processing..."
                )
                processing_time = random.uniform(1.0, 4.0)
                time.sleep(processing_time)
                print(
                    f"[{pid}] Finished task '{item.data['task_id']}' in {processing_time:.2f}s."
                )

            except TimeoutError:
                # This block is executed if no task arrives within the 5-second timeout
                print(f"[{pid}] No task received. Checking again.")
            except IndexError:
                # This would be raised if block=False was used on an empty queue
                pass

    except KeyboardInterrupt:
        print(f"\n--- Consumer (PID: {pid}) stopping. ---")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ["produce", "consume"]:
        print("Usage: python producer_consumer.py <mode>")
        print("  mode: 'produce' or 'consume'")
        sys.exit(1)

    mode = sys.argv[1]
    if mode == "produce":
        producer()
    else:
        consumer()

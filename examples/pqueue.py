from beaver import BeaverDB
import time

def priority_queue_demo():
    """Demonstrates the persistent priority queue functionality."""
    print("--- Running Priority Queue Demo ---")
    db = BeaverDB("demo.db")

    # Get a handle to a persistent priority queue named 'agent_tasks'
    tasks = db.queue("agent_tasks")

    print(f"Initial queue length: {len(tasks)}")

    # 2. Put tasks into the queue with different priorities
    # Lower number = higher priority.
    # We add them out of order to test the priority logic.
    print("\nAdding tasks with different priorities...")
    tasks.put({"action": "summarize_news", "topic": "AI"}, priority=10)
    tasks.put({"action": "respond_to_user", "user_id": "alice"}, priority=1)
    tasks.put({"action": "run_backup", "target": "all"}, priority=20)
    tasks.put({"action": "send_alert", "message": "CPU at 90%"}, priority=1)

    print(f"Queue length after adding tasks: {len(tasks)}")

    # 3. Get and process tasks in priority order
    print("\nProcessing tasks...")

    # First get should be "respond_to_user" (priority 1, added first)
    item1 = tasks.get()
    print(f"  - Got: {item1.data} (Priority: {item1.priority})")
    assert item1.data["action"] == "respond_to_user"

    # To demonstrate FIFO for same-priority items, we wait a fraction of a second
    time.sleep(0.01)

    # Second get should be "send_alert" (priority 1, added second)
    item2 = tasks.get()
    print(f"  - Got: {item2.data} (Priority: {item2.priority})")
    assert item2.data["action"] == "send_alert"

    # Third get should be "summarize_news" (priority 10)
    item3 = tasks.get()
    print(f"  - Got: {item3.data} (Priority: {item3.priority})")
    assert item3.data["action"] == "summarize_news"

    print(f"\nRemaining tasks in queue: {len(tasks)}")

    # 4. Get the last remaining task
    last_item = tasks.get()
    print(f"  - Got last item: {last_item.data} (Priority: {last_item.priority})")
    assert last_item.data["action"] == "run_backup"

    # 5. Confirm the queue is now empty
    print(f"Final queue length: {len(tasks)}")
    assert len(tasks) == 0

    db.close()
    print("\n--- Demo Finished Successfully ---")


if __name__ == "__main__":
    priority_queue_demo()

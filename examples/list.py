from beaver import BeaverDB


def list_demo():
    """Demonstrates the synchronous list functionality."""
    print("--- Running List Demo ---")
    db = BeaverDB("demo.db")

    tasks = db.list("daily_tasks")

    # Start with a clean list
    while tasks.pop() is not None:
        pass

    print(f"Initial list length: {len(tasks)}")

    # Push items to the list
    tasks.push({"task": "Write report"})
    tasks.push({"task": "Send emails"})
    tasks.prepend({"task": "Plan the day"})
    print(f"List after pushes: {tasks[0:]}") # Full slice

    # Insert an item
    tasks.insert(2, {"task": "Review PRs"})
    print(f"List after insert: {tasks[0:]}")
    print(f"Length is now: {len(tasks)}")

    # Access items by index
    print(f"First item: {tasks[0]}")
    print(f"Last item: {tasks[-1]}")

    # Pop items
    last_item = tasks.pop()
    print(f"Popped last item: {last_item}")
    first_item = tasks.deque()
    print(f"Popped first item: {first_item}")
    print(f"Final list content: {tasks[0:]}")

    db.close()
    print("-" * 35 + "\n")


if __name__ == "__main__":
    # To run this demo, save the file as beaver.py and run `python beaver.py`
    print("--- BeaverDB List Demo ---")
    list_demo()

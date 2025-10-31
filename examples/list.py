from beaver import BeaverDB


def full_featured_list_demo():
    """Demonstrates the full capabilities of the ListWrapper."""
    print("--- Running Full-Featured List Demo ---")
    db = BeaverDB("demo.db")

    tasks = db.list("project_tasks")

    # --- 1. Clean Up and Initialization ---
    # Start with a clean list for the demo
    while tasks.pop() is not None:
        pass
    print(f"Initial list state: {tasks[0:]}")

    # --- 2. Pushing and Prepending Items ---
    tasks.push({"id": "task-002", "desc": "Write documentation"})
    tasks.push({"id": "task-003", "desc": "Deploy to production"})
    tasks.prepend({"id": "task-001", "desc": "Design the feature"})
    print(f"\nAfter adding 3 tasks, length is: {len(tasks)}")

    # --- 3. Iterating Over the List ---
    print("\nCurrent tasks in order:")
    for task in tasks:
        print(f"  - {task['id']}: {task['desc']}")

    # --- 4. Accessing and Slicing ---
    print(f"\nThe first task is: {tasks[0]}")
    print(f"The last task is: {tasks[-1]}")
    print(f"A slice of the first two tasks: {tasks[0:2]}")

    # --- 5. Updating an Item in Place ---
    print("\nUpdating the second task...")
    tasks[1] = {"id": "task-002", "desc": "Write and review documentation"}
    print(f"Updated second task: {tasks[1]}")

    # --- 6. Membership Testing with `in` ---
    item_to_find = {"id": "task-001", "desc": "Design the feature"}
    print(f"\nIs '{item_to_find['id']}' in the list? {item_to_find in tasks}")

    non_existent_item = {"id": "task-999"}
    print(f"Is '{non_existent_item['id']}' in the list? {non_existent_item in tasks}")

    # --- 7. Deleting an Item by Index ---
    print("\nDeleting the first task ('task-001')...")
    del tasks[0]
    print(f"List length after deletion: {len(tasks)}")
    print(f"New first task: {tasks[0]}")

    # --- 8. Popping the Last Item ---
    last_item = tasks.pop()
    print(f"\nPopped the last task: {last_item}")
    print(f"Final list content: {tasks[0:]}")

    db.close()
    print("-" * 35 + "\n")


if __name__ == "__main__":
    full_featured_list_demo()
import random
import time
import os
import uuid
import threading
from collections import defaultdict

from beaver import BeaverDB, Document

# --- 1. State Management ---

class Stats:
    """A simple class to track the statistics of the test run."""
    def __init__(self):
        self.actions = defaultdict(int)
        self.errors = 0
        self.total_actions = 0

    def record_action(self, name):
        """Records a successful action."""
        self.actions[name] += 1
        self.total_actions += 1

    def record_error(self):
        """Records a failed action."""
        self.errors += 1
        self.total_actions += 1

# --- 2. Action Functions ---

# A collection of functions that perform random operations on the database.

def index_document(db: BeaverDB, stats: Stats):
    """Indexes a new document with random data."""
    articles = db.collection("articles")
    doc_id = str(uuid.uuid4())
    doc = Document(
        id=doc_id,
        content=f"This is a test document with random number {random.random()}",
        embedding=[random.random() for _ in range(3)],
        author=random.choice(["Alice", "Bob", "Charlie"])
    )
    articles.index(doc, fuzzy=True)
    stats.record_action("index_document")

def perform_search(db: BeaverDB, stats: Stats):
    """Performs a random search (vector, FTS, or fuzzy)."""
    articles = db.collection("articles")
    search_type = random.choice(["vector", "fts", "fuzzy"])

    if search_type == "vector":
        query_vector = [random.random() for _ in range(3)]
        articles.search(vector=query_vector, top_k=5)
    elif search_type == "fts":
        query_text = random.choice(["test", "document", "alice"])
        articles.match(query=query_text)
    else: # fuzzy
        query_text = random.choice(["tset", "documnet", "aslice"])
        articles.match(query=query_text, fuzziness=2)
    stats.record_action(f"search_{search_type}")

def list_operation(db: BeaverDB, stats: Stats):
    """Performs a random operation on a persistent list."""
    tasks = db.list("tasks")
    op = random.choice(["push", "prepend", "pop", "get"])

    if op == "push":
        tasks.push(f"task_{uuid.uuid4()}")
    elif op == "prepend":
        tasks.prepend(f"task_{uuid.uuid4()}")
    elif op == "pop":
        if len(tasks) > 0:
            tasks.pop()
    elif op == "get":
        if len(tasks) > 0:
            _ = tasks[random.randint(0, len(tasks) - 1)]
    stats.record_action(f"list_{op}")


def dict_operation(db: BeaverDB, stats: Stats):
    """Performs a random operation on a namespaced dictionary."""
    config = db.dict("config")
    op = random.choice(["set", "get", "set_ttl"])

    key = f"key_{random.randint(1, 100)}"
    if op == "set":
        config[key] = {"value": random.random()}
    elif op == "get":
        _ = config.get(key)
    elif op == "set_ttl":
        config.set(key, {"value": "with_ttl"}, ttl_seconds=5)
    stats.record_action(f"dict_{op}")

def queue_operation(db: BeaverDB, stats: Stats):
    """Puts or gets an item from a persistent priority queue."""
    task_queue = db.queue("priority_tasks")
    op = random.choice(["put", "get"])

    if op == "put":
        priority = random.randint(1, 20)
        task_queue.put({"action": "process", "id": str(uuid.uuid4())}, priority=priority)
    elif op == "get":
        if len(task_queue) > 0:
            try:
                task_queue.get()
            except IndexError:
                pass # Queue might be empty due to race condition, which is fine
    stats.record_action(f"queue_{op}")


def pubsub_operation(db: BeaverDB, stats: Stats):
    """Publishes a message to a channel."""
    channel = db.channel("live_events")
    payload = {"event": "random_update", "value": random.random()}
    channel.publish(payload)
    stats.record_action("publish_message")

# --- 3. Subscriber Thread ---

def subscriber_task(db: BeaverDB):
    """A simple task that listens for messages in the background."""
    with db.channel("live_events").subscribe() as listener:
        for _ in listener.listen():
            # In a real test, you might record stats here,
            # but for this example, we just consume the messages.
            pass

# --- 4. Main Test Runner ---

def display_stats(stats: Stats, pid: int):
    """Clears the console and displays the current statistics."""
    os.system('cls' if os.name == 'nt' else 'clear')
    print("--- BeaverDB Concurrency Stress Test ---")
    print(f"Process ID: {pid}")
    print("-" * 40)
    print(f"Total Actions: {stats.total_actions}")
    print(f"Successful: {stats.total_actions - stats.errors}")
    print(f"Errors: {stats.errors}")
    print("-" * 40)
    print("Action Breakdown:")
    for name, count in sorted(stats.actions.items()):
        print(f"  - {name:<20}: {count}")
    print("\nPress Ctrl+C to stop.")


def main():
    """The main entry point for the stress test script."""
    pid = os.getpid()
    db = BeaverDB(f"stress_test.db")
    stats = Stats()

    # Define the pool of actions the script can randomly choose from.
    actions = [
        index_document,
        perform_search,
        list_operation,
        dict_operation,
        queue_operation,
        pubsub_operation,
    ]

    # Start a background subscriber thread to test pub/sub concurrency.
    subscriber = threading.Thread(target=subscriber_task, args=(db,), daemon=True)
    subscriber.start()

    try:
        while True:
            action_to_perform = random.choice(actions)
            try:
                action_to_perform(db, stats)
            except Exception as e:
                stats.record_error()
                # Optional: Log the error to a file for debugging
                with open(f"error_log_{pid}.txt", "a") as f:
                    f.write(f"{time.time()}: {action_to_perform.__name__} -> {e}\n")

            display_stats(stats, pid)
            time.sleep(random.uniform(0.01, 0.03)) # Wait for a short, random interval

    except KeyboardInterrupt:
        print("\n--- Test stopped by user ---")

if __name__ == "__main__":
    main()
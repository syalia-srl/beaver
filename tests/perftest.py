import os
import random
import time
import uuid
from typing import List, Dict, Any, Callable

from beaver import BeaverDB, Document
from beaver.collections import CollectionManager
from beaver.dicts import DictManager
from beaver.lists import ListManager
from beaver.queues import QueueManager
from beaver.blobs import BlobManager

from rich.console import Console
from rich.table import Table

# --- Test Configuration ---

# The database file to use. It will be created and deleted for each run.
DB_PATH = "performance_test.db"

# Total number of mixed operations to perform during the timed test.
NUM_OPERATIONS = 10_000

# Number of items to pre-load into dicts, lists, etc., before the test.
SETUP_ITEMS = 1_000

# Vector dimension for collection tests.
VECTOR_DIM = 128

# --- Operation Functions ---
# These are the individual operations that will be randomly chosen.


def op_dict_write(d: DictManager):
    """Writes a random value to a random key."""
    key = f"key_{random.randint(0, SETUP_ITEMS - 1)}"
    d[key] = {"val": random.random(), "ts": time.time()}


def op_dict_read(d: DictManager):
    """Reads a random key. This will heavily benefit from caching."""
    key = f"key_{random.randint(0, SETUP_ITEMS - 1)}"
    _ = d.get(key)


def op_list_push(l: ListManager):
    """Pushes a new item to the list."""
    l.push(f"task_{uuid.uuid4()}")


def op_list_pop(l: ListManager):
    """Pops an item from the list. Handles empty list."""
    try:
        l.pop()
    except Exception:
        pass  # Ignore errors from popping an empty list


def op_queue_put(q: QueueManager):
    """Puts a new item into the priority queue."""
    q.put(f"q_task_{uuid.uuid4()}", priority=random.randint(1, 10))


def op_queue_get(q: QueueManager):
    """Gets an item from the queue. Handles empty queue."""
    try:
        q.get(block=False)
    except Exception:
        pass  # Ignore errors from getting from an empty queue


def op_coll_index(c: CollectionManager):
    """Indexes a new document with a vector."""
    embedding = [random.random() for _ in range(VECTOR_DIM)]
    doc = Document(
        id=str(uuid.uuid4()),
        embedding=embedding,
        body={"text": "random doc", "rand": random.random()},
    )
    c.index(doc)


def op_coll_search(c: CollectionManager):
    """Performs a vector search."""
    query_vec = [random.random() for _ in range(VECTOR_DIM)]
    _ = c.search(query_vec, top_k=1)


# --- Test Setup ---


def setup_data(db: BeaverDB, num_items: int):
    """Pre-populates the database with a baseline set of data."""
    console = Console()
    console.print(f"Pre-loading {num_items} items into each structure...")

    # Pre-populate managers
    d = db.dict("perf_dict")
    l = db.list("perf_list")
    q = db.queue("perf_queue")
    c = db.collection("perf_collection")

    with console.status("[bold green]Working...") as status:
        status.update("Populating Dictionary...")
        for i in range(num_items):
            d[f"key_{i}"] = {"val": 0, "ts": 0}

        status.update("Populating List...")
        for i in range(num_items):
            l.push(f"initial_task_{i}")

        status.update("Populating Queue...")
        for i in range(num_items):
            q.put(f"initial_q_task_{i}", priority=5)

        status.update("Populating Collection...")
        for i in range(num_items):
            embedding = [random.random() for _ in range(VECTOR_DIM)]
            doc = Document(id=f"doc_{i}", embedding=embedding, body={"idx": i})
            c.index(doc)

    console.print("Setup complete.")


# --- Test Runner ---


def run_test_pass(
    db: BeaverDB, num_operations: int, setup_items: int
) -> Dict[str, Any]:
    """
    Runs a full performance test pass for a given DB configuration.

    Args:
        db: An initialized BeaverDB instance.
        num_operations: Total number of random operations to perform.
        setup_items: Number of items to pre-load.

    Returns:
        A dictionary containing performance metrics.
    """
    console = Console()

    # 1. Setup Data
    setup_data(db, setup_items)

    # 2. Get managers
    d = db.dict("perf_dict")
    l = db.list("perf_list")
    q = db.queue("perf_queue")
    c = db.collection("perf_collection")

    # 3. Define the pool of operations to randomly choose from
    # We use lambdas to create functions with no arguments.
    operation_pool: List[Callable[[], None]] = [
        lambda: op_dict_write(d),
        lambda: op_dict_read(d),
        lambda: op_list_push(l),
        lambda: op_list_pop(l),
        lambda: op_queue_put(q),
        lambda: op_queue_get(q),
        lambda: op_coll_index(c),
        lambda: op_coll_search(c),
    ]

    console.print(
        f"Starting benchmark: [bold]{num_operations}[/bold] mixed operations..."
    )
    start_time = time.perf_counter()

    # 4. Run the benchmark loop
    with console.status("[bold cyan]Running operations...") as status:
        for i in range(num_operations):
            # Choose and execute a random operation
            op = random.choice(operation_pool)
            try:
                op()
            except Exception as e:
                console.log(f"Error during operation: {e}", style="bold red")

            if (i + 1) % (num_operations // 100) == 0:
                status.update(
                    f"[bold cyan]Running operations... {i+1}/{num_operations} ({((i+1)/num_operations*100):.0f}%)"
                )

    end_time = time.perf_counter()
    console.print("Benchmark finished.")

    # 5. Calculate and return metrics
    total_time = end_time - start_time
    ops_per_sec = num_operations / total_time
    avg_op_time_ms = (total_time / num_operations) * 1000

    return {
        "total_time": total_time,
        "ops_per_sec": ops_per_sec,
        "avg_op_time_ms": avg_op_time_ms,
        "cache_stats": db.cache("perf_dict").stats(),  # Check dict cache stats
    }


# --- Main Execution ---


def main():
    """
    Main function to define configurations, run tests, and print results.
    """
    console = Console()
    console.rule("[bold]BeaverDB Performance Benchmark[/bold]")
    console.print(f"Operations per run: {NUM_OPERATIONS}")
    console.print(f"Setup items per run: {SETUP_ITEMS}")

    configurations = {
        "Default": {
            "cache_timeout": 0.0,
            "pragma_wal": True,
            "pragma_synchronous": False,
        },
        "Optimized + Cache (100ms)": {
            "cache_timeout": 0.1,  # 100ms cache
            "pragma_wal": True,
            "pragma_synchronous": False,
            "pragma_mmap_size": 4 * 1024 * 1024 * 1024,
        },
        "Safe (Slowest)": {
            "cache_timeout": 0.0,
            "pragma_wal": True,
            "pragma_synchronous": True,  # Full sync
        },
    }

    all_results = []

    try:
        for name, config_params in configurations.items():
            console.rule(f"[bold cyan]Running Test: {name}[/]")

            # Clean up database file before each run
            if os.path.exists(DB_PATH):
                os.remove(DB_PATH)

            db = None
            try:
                db = BeaverDB(DB_PATH, **config_params)
                results = run_test_pass(db, NUM_OPERATIONS, SETUP_ITEMS)
                results["config_name"] = name
                all_results.append(results)
            except Exception as e:
                console.print(f"Test run failed for '{name}': {e}", style="bold red")
            finally:
                if db:
                    db.close()
                console.print("\n")

        # --- Print Summary Table ---
        console.rule("[bold]Benchmark Summary[/bold]")
        table = Table(title="Performance Results")
        table.add_column("Configuration", style="cyan", no_wrap=True)
        table.add_column("Ops/sec", style="green", justify="right")
        table.add_column("Avg. Op Time (ms)", style="yellow", justify="right")
        table.add_column("Total Time (s)", style="magenta", justify="right")
        table.add_column("Cache Hits (Dict)", style="blue", justify="right")
        table.add_column("Cache Misses (Dict)", style="blue", justify="right")

        for res in all_results:
            table.add_row(
                res["config_name"],
                f"{res['ops_per_sec']:.2f}",
                f"{res['avg_op_time_ms']:.4f}",
                f"{res['total_time']:.2f}",
                f"{res['cache_stats'].hits}",
                f"{res['cache_stats'].misses}",
            )

        console.print(table)

    finally:
        # Final cleanup
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
        console.print(f"Cleanup complete. Removed '{DB_PATH}'.")


if __name__ == "__main__":
    main()

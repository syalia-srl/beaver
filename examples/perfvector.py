import os
import time
import numpy as np
from beaver import BeaverDB, Document

# --- Configuration ---
DB_PATH = "demo.db"
COLLECTION_NAME = "large_collection"
NUM_DOCUMENTS = 1000
VECTOR_DIMENSIONS = 300
NUM_SEARCHES = 100
TOP_K = 10

def performance_benchmark():
    """
    Benchmarks indexing and searching performance for beaver-db.
    """
    # Clean up previous database file for a fresh start
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    db = BeaverDB(DB_PATH)
    docs = db.collection(COLLECTION_NAME)

    print(f"--- Starting BeaverDB Performance Benchmark ---")
    print(f"Documents: {NUM_DOCUMENTS}, Dimensions: {VECTOR_DIMENSIONS}, Searches: {NUM_SEARCHES}, K={TOP_K}")

    # --- 1. Indexing Phase ---
    print("\nIndexing documents...")
    start_time_indexing = time.perf_counter()

    # Using a list for bulk insertion is much faster with SQLite
    documents_to_index = []
    for i in range(NUM_DOCUMENTS):
        random_vector = np.random.rand(VECTOR_DIMENSIONS).tolist()
        doc = Document(
            embedding=random_vector,
            id=f"doc_{i}",
            content=f"This is document number {i}"
        )
        documents_to_index.append(doc)

    # The index method now needs to be called for each document.
    # For a real bulk operation, the BeaverDB class itself would need a bulk_index method.
    # We will loop here to simulate the public API.
    for doc in documents_to_index:
        docs.index(doc)

    end_time_indexing = time.perf_counter()
    total_indexing_time = end_time_indexing - start_time_indexing

    print(f"--- Indexing Complete ---")
    print(f"Total time to index {NUM_DOCUMENTS} documents: {total_indexing_time:.4f} seconds")
    print(f"Average time per document: {(total_indexing_time / NUM_DOCUMENTS):.4f} seconds")

    # --- 2. Searching Phase ---
    print("\nPerforming searches...")
    search_times = []
    start_time_searching = time.perf_counter()

    for _ in range(NUM_SEARCHES):
        query_vector = np.random.rand(VECTOR_DIMENSIONS).tolist()

        # Start individual search timer
        search_start = time.perf_counter()

        results = docs.search(vector=query_vector, top_k=TOP_K)

        # Stop individual search timer
        search_end = time.perf_counter()
        search_times.append(search_end - search_start)

    end_time_searching = time.perf_counter()
    total_searching_time = end_time_searching - start_time_searching

    print(f"--- Searching Complete ---")
    print(f"Total time for {NUM_SEARCHES} searches: {total_searching_time:.4f} seconds")
    print(f"Average time per search: {(np.mean(search_times)):.4f} seconds")

    db.close()


if __name__ == "__main__":
    performance_benchmark()

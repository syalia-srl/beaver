import os
import time
import random
import numpy as np
from beaver import BeaverDB, Document

# --- Configuration ---
DB_PATH = "demo.db"
COLLECTION_NAME = "product_reviews"
NUM_DOCUMENTS = 1000
NUM_SEARCHES = 100
TOP_K = 10

# --- Simple Fake Data Generation ---
# A small vocabulary to generate somewhat realistic text for searching.
NOUNS = ["product", "service", "item", "quality", "delivery", "experience", "company", "price"]
ADJECTIVES = ["great", "poor", "excellent", "terrible", "fast", "slow", "amazing", "disappointing"]
VERBS = ["was", "is", "has been", "felt"]
WORDS = NOUNS + ADJECTIVES

def generate_fake_review():
    """Generates a simple, random review sentence."""
    adj1 = random.choice(ADJECTIVES)
    noun1 = random.choice(NOUNS)
    verb = random.choice(VERBS)
    adj2 = random.choice(ADJECTIVES)
    noun2 = random.choice(NOUNS)
    return f"The {noun1} {verb} {adj1}, and the {noun2} was {adj2}."

def performance_benchmark_fts():
    """
    Benchmarks indexing and Full-Text Search (FTS) performance for beaver-db.
    """
    # Clean up previous database file for a fresh start
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    db = BeaverDB(DB_PATH)
    reviews = db.collection(COLLECTION_NAME)

    print(f"--- Starting BeaverDB FTS Performance Benchmark ---")
    print(f"Documents: {NUM_DOCUMENTS}, Searches: {NUM_SEARCHES}, K={TOP_K}")

    # --- 1. Indexing Phase ---
    print("\nIndexing documents with text content...")
    start_time_indexing = time.perf_counter()

    documents_to_index = []
    for i in range(NUM_DOCUMENTS):
        doc = Document(
            id=f"review_{i}",
            content=generate_fake_review(),
            author={
                "username": f"user_{i}",
                "rating": random.randint(1, 5)
            },
            status=random.choice(["published", "pending"])
        )
        documents_to_index.append(doc)

    # The index method handles both the vector/metadata and the FTS indexing.
    for doc in documents_to_index:
        reviews.index(doc)

    end_time_indexing = time.perf_counter()
    total_indexing_time = end_time_indexing - start_time_indexing

    print(f"--- Indexing Complete ---")
    print(f"Total time to index {NUM_DOCUMENTS} documents: {total_indexing_time:.4f} seconds")
    print(f"Average time per document: {(total_indexing_time / NUM_DOCUMENTS) * 1000:.4f} ms")

    # --- 2. Searching Phase ---
    print("\nPerforming FTS searches...")
    search_times = []
    search_results = []

    for _ in range(NUM_SEARCHES):
        # Pick a random word that is known to be in the dataset
        query_term = random.choice(WORDS)

        search_start = time.perf_counter()

        # We use the new match method
        results = reviews.match(query=query_term, top_k=TOP_K)

        search_end = time.perf_counter()
        search_times.append(search_end - search_start)
        search_results.append(len(results))

    total_searching_time = sum(search_times)

    print(f"--- Searching Complete ---")
    print(f"Total time for {NUM_SEARCHES} searches: {total_searching_time:.4f} seconds")
    print(f"Average time per search: {np.mean(search_times) * 1000:.4f} ms")
    print(f"Average results per search: {np.mean(search_results):.2f}")

    # Verify a result to ensure it's working
    print("\n--- Sample Search Result ---")
    sample_query = "great product"
    sample_results = reviews.match(query=sample_query, top_k=1)
    if sample_results:
        doc, rank = sample_results[0]
        print(f"Query: '{sample_query}'")
        print(f"Closest document found: {doc.id} (Rank: {rank:.4f})")
        print(f"  Content: '{doc.content}'")
    else:
        print("No results found for sample query.")

    db.close()


if __name__ == "__main__":
    performance_benchmark_fts()
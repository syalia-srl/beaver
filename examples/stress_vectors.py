import os
import random
import time

import numpy as np
from beaver import BeaverDB, Document


def stress_test():
    """
    A script to stress-test the vector database by indexing a large number
    of vectors and then verifying the search correctness.
    """
    DB_PATH = "stress_test.db"
    COLLECTION_NAME = "stress_test_collection"
    NUM_VECTORS = 1000
    VECTOR_DIMENSION = 128  # A common dimension for embeddings
    SEARCH_SAMPLE_SIZE = 100

    db = BeaverDB(DB_PATH)
    collection = db.collection(COLLECTION_NAME)

    print(f"--- Starting Vector DB Stress Test ---")
    print(f"Database: {DB_PATH}")
    print(f"Vectors to index: {NUM_VECTORS}")
    print(f"Vector dimension: {VECTOR_DIMENSION}")
    print("-" * 35)

    print("\n--- Phase 1: Indexing ---")
    start_time = time.time()

    # Generate all vectors in advance for efficiency
    print("Generating random vectors...")
    vectors = np.random.rand(NUM_VECTORS, VECTOR_DIMENSION).astype(np.float32)
    # Normalize vectors, which is common practice for similarity search
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)

    # Store a mapping of ID to the original vector for later verification
    indexed_data = {}

    for i in range(NUM_VECTORS):
        doc_id = f"doc_{i}"
        vector = vectors[i]
        indexed_data[doc_id] = vector

        doc = Document(id=doc_id, embedding=vector.tolist(), data=f"This is document {i}")
        collection.index(doc)

        if (i + 1) % 100 == 0:
            print(f"  Indexed {i + 1}/{NUM_VECTORS} documents...")

    end_time = time.time()
    print(f"\nIndexing finished in {end_time - start_time:.2f} seconds.")

    print("\n--- Phase 2: Search Verification ---")
    print(f"Randomly selecting {SEARCH_SAMPLE_SIZE} vectors to search for...")

    sample_ids = random.sample(list(indexed_data.keys()), SEARCH_SAMPLE_SIZE)
    success_count = 0
    search_start_time = time.time()

    for i, doc_id in enumerate(sample_ids):
        query_vector = indexed_data[doc_id]

        # Search for the top 1 closest vector
        results = collection.search(vector=query_vector.tolist(), top_k=1)

        if results:
            found_doc, distance = results[0]
            if found_doc.id == doc_id:
                success_count += 1
                print(f"  ({i+1}/{SEARCH_SAMPLE_SIZE}) ✅ Correct match for {doc_id} (Distance: {distance:.4f})")
            else:
                print(f"  ({i+1}/{SEARCH_SAMPLE_SIZE}) ❌ Incorrect match for {doc_id}. Expected {doc_id}, got {found_doc.id}")
        else:
            print(f"  ({i+1}/{SEARCH_SAMPLE_SIZE}) ❌ No results found for {doc_id}")

    search_end_time = time.time()
    print(f"\nSearch verification finished in {search_end_time - search_start_time:.2f} seconds.")

    print("\n--- Test Summary ---")
    print(f"Total documents indexed: {NUM_VECTORS}")
    print(f"Searches performed: {SEARCH_SAMPLE_SIZE}")
    print(f"Correct matches: {success_count}/{SEARCH_SAMPLE_SIZE}")

    success_rate = (success_count / SEARCH_SAMPLE_SIZE) * 100
    print(f"Success Rate: {success_rate:.1f}%")

    if success_rate >= 100.0:
        print("\n✅ Test Passed")
    else:
        print("\n❌ Test Failed")


if __name__ == "__main__":
    stress_test()

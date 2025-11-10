# examples/upsert_vector_search.py
from beaver import BeaverDB, Document


def upsert_vector_demo():
    print("--- Running Upsert Vector Search Demo ---")
    db = BeaverDB("demo.db")
    docs = db.collection("articles")

    # 1. Index documents. The first two will get auto-generated UUIDs.
    doc1 = Document(embedding=[0.1, 0.2, 0.7], text="The cat sat on the mat.")
    doc2 = Document(embedding=[0.9, 0.1, 0.1], text="A dog chased a ball.")

    # We provide a specific ID for the third document.
    doc3 = Document(
        id="article-42", embedding=[0.2, 0.2, 0.6], text="A kitten played on a rug."
    )

    docs.index(doc1)
    docs.index(doc2)
    docs.index(doc3)

    print(f"Indexed document with auto-ID: {doc1.id}")
    print(f"Indexed document with provided ID: {doc3.id}")

    # 2. Perform an upsert by re-indexing with the same ID but new data
    print("\n--- Performing Upsert ---")
    updated_doc3 = Document(
        id="article-42",
        embedding=[0.21, 0.22, 0.61],  # Slightly different vector
        text="A small cat played on a rug.",  # Updated text
        status="updated",  # Added new metadata
    )
    docs.index(updated_doc3)
    print("Upserted document with ID 'article-42'.")

    # 3. Perform a search to verify the upsert
    query_vector = [0.18, 0.20, 0.65]
    search_results = docs.search(vector=query_vector, top_k=1)

    print("\n--- Search Results (after upsert) ---")
    document, distance = search_results[0]

    print(f"Closest document found: {document}")
    print(f"  ID: {document.id}")
    print(f"  Text: {document.text}")
    print(f"  Status: {document.status}")
    print(f"  Distance: {distance:.4f}")

    db.close()


if __name__ == "__main__":
    upsert_vector_demo()

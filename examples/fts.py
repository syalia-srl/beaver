from beaver import BeaverDB, Document

def full_text_search_demo():
    """
    Demonstrates the full-text search (FTS) functionality in BeaverDB.
    """
    print("--- Running Full-Text Search Demo ---")

    # We use a separate database file for this demo
    db = BeaverDB("demo.db")
    articles = db.collection("tech_articles")

    # --- 1. Create and Index Documents with Nested Metadata ---

    # By calling articles.index(), the text fields will be automatically indexed for FTS.
    print("Indexing documents...")

    doc1 = Document(
        id="py-001",
        content="Python is a versatile programming language. Its use in data science is notable.",
        author={
            "name": "Jane Doe",
            "email": "jane.doe@example.com"
        },
        category="Programming Languages"
    )
    articles.index(doc1)

    doc2 = Document(
        id="sql-002",
        content="SQLite is a powerful embedded database. It is ideal for local applications.",
        author={
            "name": "John Smith",
            "handle": "@john_smith_sql"
        },
        category="Databases"
    )
    articles.index(doc2)

    doc3 = Document(
        id="py-dev-003",
        content="Web application development with Python is made easier with frameworks like Django.",
        author={
            "name": "Jane Doe", # Same author as doc1
            "email": "jane.doe@example.com"
        },
        category="Web Development"
    )
    articles.index(doc3)

    print("Documents indexed.\n")

    # --- 2. Perform a General Full-Text Search ---

    # We search for the word "data" across ALL text fields in all documents.
    # It should find both doc1 ("data science") and doc2 ("Databases").
    print("--- General Search for 'data' ---")
    general_results = articles.match("data", top_k=5)

    for doc, rank in general_results:
        print(f"  - Document ID: {doc.id}, Relevance (Rank): {rank:.4f}")
        print(f"    Content: '{doc.content[:40]}...'")
        print(f"    Author: {doc.author['name']}")

    # --- 3. Perform a Targeted Full-Text Search on a Specific Field ---

    # Now, we search for "Jane" but ONLY in the flattened 'author__name' field.
    # This should return only the documents by Jane Doe (doc1 and doc3).
    print("\n--- Specific Search for 'Jane' in the 'author__name' field ---")
    specific_results = articles.match("Jane", on_field="author__name", top_k=5)

    for doc, rank in specific_results:
        print(f"  - Document ID: {doc.id}, Relevance (Rank): {rank:.4f}")
        print(f"    Author Found: {doc.author['name']}")
        print(f"    Category: {doc.category}")

    # --- 4. Use FTS5 Operators ---

    # FTS5 allows for operators like OR. We search for documents containing "SQLite" OR "Django".
    print("\n--- Search with 'OR' Operator: 'SQLite OR Django' ---")
    or_results = articles.match("SQLite OR Django", top_k=5)

    for doc, rank in or_results:
        print(f"  - Document ID: {doc.id}, Relevance (Rank): {rank:.4f}")
        print(f"    Content: '{doc.content}'")

    db.close()
    print("\n--- Demo Finished ---")


if __name__ == "__main__":
    full_text_search_demo()
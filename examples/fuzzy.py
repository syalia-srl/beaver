from beaver import BeaverDB, Document


def fuzzy_search_demo():
    """Demonstrates the unified FTS and fuzzy search functionality."""
    print("--- Running Fuzzy Search Demo ---")
    db = BeaverDB("fuzzy_demo.db")
    articles = db.collection("tech_articles")

    # Clean up from previous runs
    for doc in articles:
        articles.drop(doc)

    # --- 1. Index Documents with Fuzzy Indexing Enabled ---
    print("Indexing documents with fuzzy=True...")
    docs_to_index = [
        Document(
            id="py-001",
            content="Python is a versatile programming language.",
            author={"name": "Jane Doe", "handle": "janedoe_py"},
        ),
        Document(
            id="sql-002",
            content="SQLite is a powerful embedded database.",
            author={"name": "Jon Smith", "handle": "jonsmith_sql"},
        ),
        Document(
            id="py-dev-003",
            content="Web development with python is easier with frameworks.",
            author={"name": "Jane Doe", "handle": "janedoe_py"},
        ),
    ]

    for doc in docs_to_index:
        # Index all string fields for FTS and also create a fuzzy index for them
        articles.index(doc, fts=True, fuzzy=True)

    # --- 2. Standard FTS Search (fuzziness=0) ---
    print("\n--- Standard FTS for 'python' ---")
    exact_results = articles.match("python", fuzziness=0)
    for doc, rank in exact_results:
        print(f"  - Found ID: {doc.id} (Rank: {rank:.2f})")

    # --- 3. Fuzzy Search on a Specific Field ---
    # Search for "Jhn Smith" with a typo. It should find "Jon Smith".
    print("\n--- Fuzzy Search for 'Jhn Smith' on 'author.name' ---")
    fuzzy_results = articles.match(
        "Jhn Smith",
        on=["author.name"],
        fuzziness=2
    )
    for doc, distance in fuzzy_results:
        print(f"  - Found: '{doc.author['name']}' (Distance: {distance})")
        assert doc.id == "sql-002"

    # --- 4. Fuzzy Search Across All Fields ---
    # Search for "prgramming" with a typo. It should find the doc with "programming".
    print("\n--- Fuzzy Search for 'prgramming' across all fields ---")
    fuzzy_all_fields = articles.match("prgramming", fuzziness=2)
    for doc, distance in fuzzy_all_fields:
        print(f"  - Found in content: '{doc.content}' (Distance: {distance})")
        assert doc.id == "py-001"

    db.close()
    print("\n--- Demo Finished ---")


if __name__ == "__main__":
    fuzzy_search_demo()

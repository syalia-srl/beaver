from beaver import BeaverDB, Document
from beaver.collections import rerank


# --- 1. Setup and Data Indexing ---
db = BeaverDB("tech_articles.db")
articles = db.collection("articles")

# Let's create documents about programming languages.
# Note: Vectors are simplified for clarity.
docs_to_index = [
    Document(
        id="py-fast",
        embedding=[0.1, 0.9, 0.2], # Vector leans towards "speed"
        content="Python is a great language for fast prototyping and development."
    ),
    Document(
        id="py-data",
        embedding=[0.8, 0.2, 0.9], # Vector leans towards "data science"
        content="The Python ecosystem is ideal for data science and machine learning."
    ),
    Document(
        id="js-fast",
        embedding=[0.2, 0.8, 0.1], # Vector similar to "py-fast"
        content="JavaScript engines are optimized for fast execution in the browser."
    )
]

for doc in docs_to_index:
    articles.index(doc)

# --- 2. Perform Two Different Searches ---

# Case: The user is interested in "fast python"

# Keyword Search: "python"
# This will find documents that explicitly mention the word "python".
keyword_query = "python"
keyword_results = [doc for doc, rank in articles.match(query=keyword_query)]

# Vector Search: A query vector representing "high-performance code"
# This will find documents that are semantically similar, even without the exact keywords.
vector_query = [0.15, 0.85, 0.15] # A vector close to "fast"
vector_results = [doc for doc, score in articles.search(vector=vector_query)]


print("--- INDIVIDUAL SEARCH RESULTS ---")
print(f"Keyword search for '{keyword_query}': {[d.id for d in keyword_results]}")
print(f"Vector search for 'high-performance': {[d.id for d in vector_results]}")


# --- 3. Rerank to Get a Hybrid Result ---

# We have two lists:
# - keyword_results: ['py-fast', 'py-data']
# - vector_results:  ['py-fast', 'js-fast', 'py-data']
#
# The document "py-fast" is ranked high in both. Reranking should promote it to the top.
final_ranked_list = rerank(keyword_results, vector_results)

print("\n--- FINAL RERANKED RESULTS ---")
print("Combined and reranked order:", [d.id for d in final_ranked_list])
for doc in final_ranked_list:
    print(f"  - {doc.id}: {doc.content}")

db.close()

# The Document Collection (`db.collection`)

**Chapter Outline:**

* **5.1. Documents & Indexing**
    * The `Document` class: `id`, `embedding`, and `metadata`.
    * Indexing and Upserting: `.index(doc)` performs an atomic insert-or-replace.
    * Removing data: `.drop(doc)`.
* **5.2. Vector Search (ANN)**
    * Adding vectors via the `Document(embedding=...)` field.
    * Querying: `.search(vector, top_k=N)`.
    * **Use Case:** Building a RAG system by combining text and vector search.
    * **Helper:** The `rerank()` function for hybrid search results.
* **5.3. Full-Text & Fuzzy Search**
    * Full-Text Search (FTS): `.match(query, on=["field.path"])`.
    * Fuzzy Search: `.match(query, fuzziness=2)` for typo-tolerance.
* **5.4. Knowledge Graph**
    * Creating relationships: `.connect(source, target, label, metadata)`.
    * Single-hop traversal: `.neighbors(doc, label)`.
    * Multi-hop (BFS) traversal: `.walk(source, labels, depth, direction)`.

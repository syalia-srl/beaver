# Collections (Multi-Modal Search)

The `CollectionManager` is the powerhouse of BeaverDB. It provides a unified interface for storing Documents and performing **Vector Search**, **Full-Text Search (FTS)**, **Fuzzy Matching**, and **Graph Traversal** on them.

This is ideal for building RAG (Retrieval Augmented Generation) applications, search engines, knowledge graphs, or recommendation systems.

## Quick Start

A Collection stores `Document` objects. Each document has a unique `id`, an optional vector `embedding`, and a JSON-serializable `body`.

```python
from beaver import BeaverDB
from beaver.collections import Document

db = BeaverDB("app.db")
docs = db.collection("articles")

# 1. Index a Document (with embedding for semantic search)
doc = Document(
    id="doc_1",
    body={"title": "Introduction to AI", "content": "AI is changing the world..."},
    embedding=[0.1, 0.2, 0.8, ...] # 768-dim vector
)
docs.index(doc)

# 2. Semantic Search (Vector)
# Finds documents semantically similar to the query vector
results = docs.search(query_vector, top_k=5)

# 3. Keyword Search (FTS)
# Finds documents containing specific words
matches = docs.match("artificial intelligence")
```

## Managing Documents

### The `Document` Object

BeaverDB uses a strict Pydantic model for items.

  * **`id`**: String (UUID by default).
  * **`embedding`**: List of floats (or None).
  * **`body`**: Dictionary or Pydantic model (Metadata).

<!-- end list -->

```python
from pydantic import BaseModel

class Article(BaseModel):
    title: str
    tags: list[str]

# Typed Collection
articles = db.collection("news", model=Article)

# Indexing
articles.index(Document(body=Article(title="New Release", tags=["tech"])))
```

### Indexing

The `.index()` method performs an atomic upsert. It updates the main storage, vector index, FTS index, and fuzzy n-gram index simultaneously.

```python
# Index with specific FTS fields
docs.index(doc, fts=["title", "content"])

# Enable Fuzzy Search support (slower indexing, robust matching)
docs.index(doc, fts=["title"], fuzzy=True)
```

### Deleting & Clearing

```python
# Remove a single document
docs.drop(doc)

# Wipe the entire collection (Vectors, Graph, FTS)
docs.clear()
```

## Search Capabilities

### 1. Vector Search (Semantic)

Performs an Approximate Nearest Neighbor (ANN) search using Cosine Similarity.

  * **Speed:** Extremely fast (in-memory index).
  * **Persistence:** The index is fully persisted to disk and crash-safe.

<!-- end list -->

```python
# Returns list of (Document, score) tuples
results = docs.search(embedding_vector, top_k=10)

for doc, score in results:
    print(f"{score:.4f}: {doc.body['title']}")
```

### 2. Full-Text Search (FTS)

Uses SQLite's FTS5 engine for powerful keyword matching. Supports boolean operators (`AND`, `OR`, `NOT`) and prefix matching.

```python
# Simple match
docs.match("python database")

# Specific fields
docs.match("tutorial", on=["title"])

# Boolean query
docs.match("python AND NOT java")
```

### 3. Fuzzy Search (Typo Tolerance)

If you indexed with `fuzzy=True`, you can find documents even with typos. BeaverDB uses a hybrid **Trigram + Levenshtein** approach for high performance.

```python
# Finds "BeaverDB" even if user types "BaverDB"
docs.match("BaverDB", fuzziness=1)
```

### 4. Hybrid Search (Reranking)

To get the best of both worlds (semantic understanding + keyword precision), use **Reverse Rank Fusion (RRF)**. BeaverDB provides a built-in `rerank` helper.

```python
from beaver.collections import rerank

# 1. Run searches in parallel
vector_hits = [doc for doc, _ in docs.search(vec, top_k=50)]
keyword_hits = [doc for doc, _ in docs.match("query", top_k=50)]

# 2. Fuse results
# Scores are normalized based on rank position
final_results = rerank(vector_hits, keyword_hits, k=60)
```

## Graph & Relationships

BeaverDB is also a **Graph Database**. You can link documents together and traverse the connections to find related context (e.g., for GraphRAG).

### Linking Documents

Create directed, labeled edges between documents.

```python
# d1 -> d2 (d1 references d2)
docs.connect(d1, d2, label="references")

# d2 -> d3 (d2 is the parent of d3)
docs.connect(d2, d3, label="parent")
```

### Neighbors & Traversal

Retrieve connected documents efficiently.

```python
# Get immediate neighbors
refs = docs.neighbors(d1, label="references")

# Multi-hop Traversal (BFS)
# "Find everything d1 connects to, up to 2 hops away"
# This runs a Recursive CTE in SQLite (Very Fast)
context = docs.walk(d1, labels=["references", "parent"], depth=2)
```

## Maintenance

### Compaction

The vector index uses a **Hybrid Architecture** (Base Snapshot + Delta Log). Over time, the delta log grows.

  * **Auto-Compaction:** Triggered automatically when the log gets too large.
  * **Manual Compaction:** You can force a merge of the log into the main index.

```python
docs.compact()
```

### Exporting

Dump the entire collection (vectors and metadata) to JSON for backup.

```python
data = docs.dump()
# OR write directly to file
with open("backup.json", "w") as f:
    docs.dump(f)
```

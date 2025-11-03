import pytest
from beaver import BeaverDB, Document

pytestmark = pytest.mark.unit

# --- Test Data Fixtures ---

# A set of documents with text metadata for FTS/fuzzy tests
@pytest.fixture
def text_docs():
    return [
        Document(
            id="py",
            content="Python is a great programming language.",
            author="Guido"
        ),
        Document(
            id="sql",
            content="SQLite is a powerful database.",
            author="Richard"
        ),
        Document(
            id="js",
            content="JavaScript is a language for web programming.",
            author="Brendan"
        )
    ]

# A set of documents with vector embeddings for search tests
@pytest.fixture
def vector_docs():
    return [
        Document(
            id="cat",
            embedding=[0.1, 0.1, 0.9], # Vector for "cat"
            content="A small feline."
        ),
        Document(
            id="dog",
            embedding=[0.9, 0.1, 0.1], # Vector for "dog"
            content="A loyal canine."
        ),
        Document(
            id="person",
            embedding=[0.1, 0.9, 0.1], # Vector for "person"
            content="A human being."
        )
    ]

# --- Test Cases ---

# 1. Core Indexing and Lifecycle

def test_collection_index_and_len(db_memory: BeaverDB):
    """Tests that indexing documents increases the collection length."""
    coll = db_memory.collection("test_index_len")
    assert len(coll) == 0

    doc1 = Document(id="d1", content="doc one")
    coll.index(doc1)

    assert len(coll) == 1

def test_collection_index_upsert_and_iter(db_memory: BeaverDB):
    """Tests that indexing with an existing ID overwrites (upserts) the document."""
    coll = db_memory.collection("test_upsert_iter")

    doc_v1 = Document(id="d1", content="version 1", status="old")
    coll.index(doc_v1)
    assert len(coll) == 1

    # Re-index with the same ID
    doc_v2 = Document(id="d1", content="version 2", status="new")
    coll.index(doc_v2)

    # Length should remain 1
    assert len(coll) == 1

    # Check that the content was updated by iterating
    items = list(coll)
    assert len(items) == 1
    assert items[0].id == "d1"
    assert items[0].content == "version 2"
    assert items[0].status == "new" # Verify new metadata is present

def test_collection_drop(db_memory: BeaverDB):
    """Tests that dropping a document removes it from the collection."""
    coll = db_memory.collection("test_drop")

    doc1 = Document(id="d1", content="doc one")
    doc2 = Document(id="d2", content="doc two")
    coll.index(doc1)
    coll.index(doc2)
    assert len(coll) == 2

    coll.drop(doc1)
    assert len(coll) == 1

    items = list(coll)
    assert items[0].id == "d2" # Only doc2 should remain

    coll.drop(doc2)
    assert len(coll) == 0

# 2. Vector Search Tests

def test_vector_search(db_memory: BeaverDB, vector_docs):
    """Tests vector search for correctness and top_k."""
    coll = db_memory.collection("test_vector_search")
    for doc in vector_docs:
        coll.index(doc)

    assert len(coll) == 3

    # Query vector very close to "cat" ([0.1, 0.1, 0.9])
    query_cat = [0.1, 0.2, 0.8]

    # Test top_k=1
    results_k1 = coll.search(query_cat, top_k=1)
    assert len(results_k1) == 1
    found_doc, distance = results_k1[0]
    assert found_doc.id == "cat"
    assert distance >= 0

    # Test top_k=3
    results_k3 = coll.search(query_cat, top_k=3)
    assert len(results_k3) == 3

    # The first result should still be 'cat'
    assert results_k3[0][0].id == "cat"
    # The other two should also be present
    result_ids = {doc.id for doc, dist in results_k3}
    assert result_ids == {"cat", "dog", "person"}

def test_vector_search_no_results(db_memory: BeaverDB):
    """Tests that vector search returns an empty list when collection is empty."""
    coll = db_memory.collection("test_vector_empty")
    results = coll.search([0.1, 0.2, 0.3], top_k=1)
    assert results == []

# 3. Full-Text Search (FTS) and Fuzzy Search

def test_fts_match_default(db_memory: BeaverDB, text_docs):
    """Tests standard FTS (fuzziness=0) across all indexed text fields."""
    coll = db_memory.collection("test_fts")
    for doc in text_docs:
        coll.index(doc, fts=True)

    # "language" is in "py" and "js"
    results = coll.match("language")
    assert len(results) == 2
    result_ids = {doc.id for doc, rank in results}
    assert result_ids == {"py", "js"}

def test_fts_match_on_field(db_memory: BeaverDB, text_docs):
    """Tests FTS restricted to a specific metadata field."""
    coll = db_memory.collection("test_fts_on")
    for doc in text_docs:
        coll.index(doc, fts=True)

    # "Guido" only exists in the 'author' field of doc 'py'
    # We also add another doc that has "Guido" in the 'content'
    coll.index(Document(id="bio", content="A bio about Guido"), fts=True)

    # Search for "Guido" only on the 'author' field
    results = coll.match("Guido", on=["author"])

    assert len(results) == 1
    assert results[0][0].id == "py"

def test_fuzzy_match(db_memory: BeaverDB, text_docs):
    """Tests fuzzy search (fuzziness > 0) for typos."""
    coll = db_memory.collection("test_fuzzy")
    for doc in text_docs:
        # Must enable both fts and fuzzy for fuzzy to work
        coll.index(doc, fts=True, fuzzy=True)

    # "prgramming" is a typo for "programming" (in "py" and "js")
    # Levenshtein distance is 2
    results = coll.match("prgramming", fuzziness=2)

    assert len(results) > 0
    result_ids = {doc.id for doc, dist in results}
    assert "py" in result_ids
    assert "js" in result_ids

def test_fuzzy_match_requires_fts_and_fuzzy_flags(db_memory: BeaverDB, text_docs):
    """Tests that fuzzy search finds no results if flags weren't set at index time."""
    coll = db_memory.collection("test_fuzzy_flags")

    # Index doc 'py' with fts=True but fuzzy=False
    coll.index(text_docs[0], fts=True, fuzzy=False)

    # Index doc 'js' with fts=False but fuzzy=True
    coll.index(text_docs[2], fts=False, fuzzy=True)

    # Search for typo "prgramming". Neither doc should be found.
    results = coll.match("prgramming", fuzziness=2)
    assert len(results) == 0

from beaver import BeaverDB, Document, WalkDirection

# ... (Keep the existing fixtures: text_docs, vector_docs) ...

@pytest.fixture
def graph_docs(db_memory: BeaverDB):
    """A fixture to index a set of documents and connect them as a graph."""
    coll = db_memory.collection("test_graph")

    docs = {
        "alice": Document(id="alice", name="Alice"),
        "bob": Document(id="bob", name="Bob"),
        "charlie": Document(id="charlie", name="Charlie"),
        "diana": Document(id="diana", name="Diana"),
    }

    for doc in docs.values():
        coll.index(doc)

    # Create graph:
    # Alice -> FOLLOWS -> Bob -> FOLLOWS -> Diana
    # Alice -> FOLLOWS -> Charlie
    # Charlie -> FOLLOWS -> Bob
    # Alice -> COLLABORATES_WITH -> Bob

    coll.connect(docs["alice"], docs["bob"], label="FOLLOWS")
    coll.connect(docs["alice"], docs["charlie"], label="FOLLOWS")
    coll.connect(docs["bob"], docs["diana"], label="FOLLOWS")
    coll.connect(docs["charlie"], docs["bob"], label="FOLLOWS")
    coll.connect(docs["alice"], docs["bob"], label="COLLABORATES_WITH")

    return coll, docs

# --- Graph Method Tests ---

def test_graph_connect_and_neighbors(graph_docs):
    """Tests that connect creates edges and neighbors finds them."""
    coll, docs = graph_docs

    # Test Alice's neighbors (should be Bob and Charlie, regardless of label)
    alice_neighbors = coll.neighbors(docs["alice"])

    assert len(alice_neighbors) == 2 # Bob and Charlie
    neighbor_ids = {doc.id for doc in alice_neighbors}
    assert "bob" in neighbor_ids
    assert "charlie" in neighbor_ids

def test_graph_neighbors_with_label(graph_docs):
    """Tests filtering neighbors by a specific edge label."""
    coll, docs = graph_docs

    # Test Alice's "FOLLOWS" neighbors
    alice_follows = coll.neighbors(docs["alice"], label="FOLLOWS")
    assert len(alice_follows) == 2
    assert {doc.id for doc in alice_follows} == {"bob", "charlie"}

    # Test Alice's "COLLABORATES_WITH" neighbors
    alice_collabs = coll.neighbors(docs["alice"], label="COLLABORATES_WITH")
    assert len(alice_collabs) == 1
    assert alice_collabs[0].id == "bob"

    # Test neighbors with a non-existent label
    alice_empty = coll.neighbors(docs["alice"], label="ENEMIES")
    assert len(alice_empty) == 0

def test_graph_walk_outgoing(graph_docs):
    """Tests a multi-hop (depth=2) outgoing walk."""
    coll, docs = graph_docs

    # Find everyone Alice "FOLLOWS" up to 2 steps away
    # Depth 1: Bob, Charlie
    # Depth 2: Diana (via Bob)
    foaf = coll.walk(
        source=docs["alice"],
        labels=["FOLLOWS"],
        depth=2,
        direction=WalkDirection.OUTGOING
    )

    assert len(foaf) == 3
    foaf_ids = {doc.id for doc in foaf}
    assert foaf_ids == {"bob", "charlie", "diana"}

def test_graph_walk_incoming(graph_docs):
    """Tests an incoming walk to find followers."""
    coll, docs = graph_docs

    # Find who "FOLLOWS" Bob (depth 1)
    # Should be Alice and Charlie
    followers = coll.walk(
        source=docs["bob"],
        labels=["FOLLOWS"],
        depth=1,
        direction=WalkDirection.INCOMING
    )

    assert len(followers) == 2
    follower_ids = {doc.id for doc in followers}
    assert follower_ids == {"alice", "charlie"}

def test_graph_walk_multi_label(graph_docs):
    """Tests walking with multiple labels."""
    coll, docs = graph_docs

    # Find all connections from Alice (depth 1)
    connections = coll.walk(
        source=docs["alice"],
        labels=["FOLLOWS", "COLLABORATES_WITH"],
        depth=1,
        direction=WalkDirection.OUTGOING
    )

    # Should find Bob (twice, but walk returns distinct) and Charlie
    assert len(connections) == 2
    connection_ids = {doc.id for doc in connections}
    assert connection_ids == {"bob", "charlie"}

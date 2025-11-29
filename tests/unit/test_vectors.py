import pytest
from beaver import AsyncBeaverDB, q

pytestmark = pytest.mark.asyncio


async def test_vector_basic_crud(async_db_mem: AsyncBeaverDB):
    """Test add, get, delete."""
    vecs = async_db_mem.vectors("embeddings")

    # Set
    await vecs.set("v1", [0.1, 0.2], metadata={"label": "A"})

    # Get
    item = await vecs.get("v1")
    assert item.id == "v1"
    # Floating point comparison approximation
    assert abs(item.vector[0] - 0.1) < 1e-6
    assert item.metadata and item.metadata["label"] == "A"

    # Delete
    await vecs.delete("v1")

    with pytest.raises(KeyError):
        await vecs.get("v1")


async def test_vector_search(async_db_mem: AsyncBeaverDB):
    """Test KNN search."""
    vecs = async_db_mem.vectors("search_test")

    # Insert vectors:
    # A: [1, 0]
    # B: [0, 1]
    # C: [0.9, 0.1] (Close to A)
    await vecs.set("A", [1.0, 0.0])
    await vecs.set("B", [0.0, 1.0])
    await vecs.set("C", [0.9, 0.1])

    # Search for something close to A
    results = await vecs.search([0.95, 0.05], k=2)

    # Expect: A (closest), then C (next closest)
    assert len(results) == 2
    assert results[0].id == "A"
    assert results[1].id == "C"
    assert results[0].score > results[1].score


async def test_vector_metadata_model(async_db_mem: AsyncBeaverDB):
    """Test using Pydantic model for metadata."""
    from pydantic import BaseModel

    class Meta(BaseModel):
        tag: str

    vecs = async_db_mem.vectors("typed", model=Meta)

    await vecs.set("x", [0.5, 0.5], metadata=Meta(tag="center"))

    item = await vecs.get("x")
    assert isinstance(item.metadata, Meta)
    assert item.metadata.tag == "center"


async def test_vector_search_subset_whitelist(async_db_mem: AsyncBeaverDB):
    """Test restricting vector search to a specific list of IDs (Pre-filtering)."""
    vecs = async_db_mem.vectors("whitelist_test")

    # A is closest to Query, but we will exclude it from candidate_ids
    # B is further, but will be included
    await vecs.set("A", [1.0, 0.0]) # Target
    await vecs.set("B", [0.0, 1.0]) # Orthogonal
    await vecs.set("C", [0.5, 0.5]) # Middle

    query = [1.0, 0.0]

    # 1. Normal Search -> Finds A
    normal_results = await vecs.search(query, k=1)
    assert normal_results[0].id == "A"

    # 2. Subset Search -> Restrict to B and C (Exclude A)
    # The search should strictly ignore A, even though it's the best match
    subset_results = await vecs.search(query, candidate_ids=["B", "C"], k=1)

    assert len(subset_results) == 1
    assert subset_results[0].id == "C"  # C is closest among the allowed candidates


async def test_vector_search_metadata_filtering(async_db_mem: AsyncBeaverDB):
    """Test pushing metadata filters down to the vector search."""
    vecs = async_db_mem.vectors("filter_test")

    # Insert with metadata
    await vecs.set("v1", [1.0, 0.0], metadata={"category": "sports", "views": 100})
    await vecs.set("v2", [1.0, 0.0], metadata={"category": "news",   "views": 500})
    await vecs.set("v3", [0.9, 0.0], metadata={"category": "sports", "views": 10})

    query = [1.0, 0.0]

    # 1. Filter by Category (Equality)
    # Should find v1 (exact match, sports) and skip v2 (news)
    results_sports = await vecs.search(
        query,
        filters=[q("category") == "sports"],
        k=10
    )

    ids = [r.id for r in results_sports]
    assert "v1" in ids
    assert "v3" in ids
    assert "v2" not in ids

    # 2. Filter by Numeric Range (Views > 200)
    # Should find only v2
    results_popular = await vecs.search(
        query,
        filters=[q("views") > 200],
        k=10
    )
    assert len(results_popular) == 1
    assert results_popular[0].id == "v2"

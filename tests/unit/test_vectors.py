import asyncio
import pytest
from beaver import AsyncBeaverDB

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

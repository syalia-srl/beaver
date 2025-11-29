import asyncio
import pytest
from beaver import AsyncBeaverDB

pytestmark = pytest.mark.asyncio


async def test_graph_link_unlink(async_db_mem: AsyncBeaverDB):
    """Test basic edge creation, existence check, and deletion."""
    g = async_db_mem.graph("social")

    # Link
    await g.link("alice", "bob", "follows")
    assert await g.linked("alice", "bob", "follows") is True

    # Unlink
    await g.unlink("alice", "bob", "follows")
    assert await g.linked("alice", "bob", "follows") is False


async def test_graph_get_metadata(async_db_mem: AsyncBeaverDB):
    """Test retrieving full edge with metadata."""
    g = async_db_mem.graph("meta")
    await g.link("a", "b", "friend", metadata={"since": 2020})

    # Get existing
    edge = await g.get("a", "b", "friend")
    assert edge.source == "a"
    assert edge.target == "b"
    assert edge.metadata["since"] == 2020

    # Get missing
    with pytest.raises(KeyError):
        await g.get("a", "c", "friend")


async def test_graph_traversal(async_db_mem: AsyncBeaverDB):
    """Test children (outgoing) and parents (incoming) traversal."""
    g = async_db_mem.graph("tree")

    # Structure:
    #       Root
    #      /    \
    #   Leaf1  Leaf2

    await g.link("root", "leaf1", "parent_of")
    await g.link("root", "leaf2", "parent_of")

    # 1. Children of Root
    children = []
    async for c in g.children("root", label="parent_of"):
        children.append(c)
    assert sorted(children) == ["leaf1", "leaf2"]

    # 2. Parents of Leaf1
    parents = []
    async for p in g.parents("leaf1", label="parent_of"):
        parents.append(p)
    assert parents == ["root"]


async def test_graph_edges_iterator(async_db_mem: AsyncBeaverDB):
    """Test iterating over Edge objects."""
    g = async_db_mem.graph("edges")
    await g.link("x", "y", "link1")
    await g.link("x", "z", "link2")

    edges = []
    async for e in g.edges("x"):
        edges.append((e.target, e.label))

    assert sorted(edges) == [("y", "link1"), ("z", "link2")]

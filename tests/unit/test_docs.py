import asyncio
import pytest
from pydantic import BaseModel
from beaver import AsyncBeaverDB, Document

pytestmark = pytest.mark.asyncio


class Article(BaseModel):
    title: str
    content: str
    tags: list[str]


async def test_docs_basic_crud(async_db_mem: AsyncBeaverDB):
    """Test index, get, drop with simple strings."""
    docs = async_db_mem.docs("notes", model=str)

    # 1. Index (auto ID)
    doc1 = await docs.index(body="Remember to buy milk")
    assert doc1.id is not None
    assert doc1.body == "Remember to buy milk"

    # 2. Get
    retrieved = await docs.get(doc1.id)
    assert retrieved.body == doc1.body

    # 3. Drop
    await docs.drop(doc1.id)

    with pytest.raises(KeyError):
        await docs.get(doc1.id)


async def test_docs_flexible_arguments(async_db_mem: AsyncBeaverDB):
    """Test the different calling signatures of index()."""
    docs = async_db_mem.docs("flex")

    # index(doc)
    d1 = Document(id="1", body="one")
    await docs.index(d1)
    assert (await docs.get("1")).body == "one"

    # index(id, body)
    await docs.index(id="2", body="two")
    assert (await docs.get("2")).body == "two"

    # index(body) -> auto id
    d3 = await docs.index(body="three")
    assert (await docs.get(d3.id)).body == "three"


async def test_docs_pydantic_model(async_db_mem: AsyncBeaverDB):
    """Test storing structured Pydantic models."""

    class User(BaseModel):
        name: str
        role: str

    docs = async_db_mem.docs("users", model=User)
    user = User(name="Alice", role="admin")

    # Index
    await docs.index(id="alice", body=user)

    # Retrieve (Should be re-hydrated into User model)
    doc = await docs.get("alice")
    assert isinstance(doc.body, User)
    assert doc.body.name == "Alice"


async def test_docs_field_search(async_db_mem: AsyncBeaverDB):
    """Test searching on specific fields using the new FTS implementation."""
    docs = async_db_mem.docs("news", model=Article)

    # Doc 1: "Python" in title
    await docs.index(
        body=Article(title="Python News", content="Something else", tags=[])
    )

    # Doc 2: "Python" in body
    await docs.index(body=Article(title="Coding", content="I love Python", tags=[]))

    # Doc 3: "Python" in tags
    await docs.index(
        body=Article(title="Snake", content="Hiss", tags=["reptile", "python"])
    )

    # 1. Search ANY field
    results = await docs.search("Python")
    assert len(results) == 3

    # 2. Search TITLE only
    results_title = await docs.search("Python", on=["title"])
    assert len(results_title) == 1
    assert results_title[0].body.title == "Python News"

    # 3. Search TAGS only
    results_tags = await docs.search("python", on=["tags"])
    assert len(results_tags) == 1
    assert results_tags[0].body.title == "Snake"


async def test_docs_fuzzy_search(async_db_mem: AsyncBeaverDB):
    """Test fuzzy search using trigrams."""
    docs = async_db_mem.docs("fuzzy_test", model=str)

    await docs.index(body="The quick brown fox")
    await docs.index(body="The qick brown fx")  # Typo
    await docs.index(body="Completely different text")

    # Exact search shouldn't find the typo
    results_exact = await docs.search("quick").execute()
    assert len(results_exact) == 1

    # Fuzzy search should find both "quick" and "qick" (similar trigrams)
    # "quick": qui, uic, ick
    # "qick": qic, ick
    # Overlap: ick
    results_fuzzy = await docs.fuzzy("quick").execute()
    assert len(results_fuzzy) >= 2
    assert results_fuzzy[0].body == "The quick brown fox"
    assert results_fuzzy[1].body == "The qick brown fx"


async def test_docs_fluent_query(async_db_mem: AsyncBeaverDB):
    """Test fluent query API: filter, sort, limit."""

    class Product(BaseModel):
        name: str
        price: float
        category: str

    docs = async_db_mem.docs("shop", model=Product)

    await docs.index(body=Product(name="Laptop", price=1000, category="tech"))
    await docs.index(body=Product(name="Phone", price=500, category="tech"))
    await docs.index(body=Product(name="Apple", price=1, category="food"))

    # Filter + Sort
    results = await (
        docs.query().where("category", "tech").sort("price", "DESC").execute()
    )

    assert len(results) == 2
    assert results[0].body.name == "Laptop"
    assert results[1].body.name == "Phone"

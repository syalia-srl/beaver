import asyncio
import pytest
from beaver import AsyncBeaverDB

pytestmark = pytest.mark.asyncio


async def test_blob_put_get(async_db_mem: AsyncBeaverDB):
    """Test basic binary storage."""
    b = async_db_mem.blob("images")
    data = b"\x89PNG\r\n\x1a\n"

    await b.put("logo.png", data)

    # Verify retrieval
    retrieved = await b.get("logo.png")
    assert retrieved == data
    assert isinstance(retrieved, bytes)


async def test_blob_metadata(async_db_mem: AsyncBeaverDB):
    """Test storing and retrieving metadata."""
    b = async_db_mem.blob("docs")
    pdf_data = b"%PDF-1.4..."
    meta = {"author": "alice", "pages": 10}

    await b.put("report.pdf", pdf_data, metadata=meta)

    # fetch() returns the full item
    item = await b.fetch("report.pdf")
    assert item.key == "report.pdf"
    assert item.data == pdf_data
    assert item.metadata == meta


async def test_blob_dict_access(async_db_mem: AsyncBeaverDB):
    """Test dictionary-style set/get/del aliases."""
    b = async_db_mem.blob("cache")

    # Set (__setitem__ -> set)
    await b.set("file1", b"content1")

    # Get (__getitem__ -> get)
    assert await b.get("file1") == b"content1"

    # Contains (__contains__)
    assert await b.contains("file1") is True

    # Delete (__delitem__ -> delete)
    await b.delete("file1")
    assert await b.contains("file1") is False

    with pytest.raises(KeyError):
        await b.get("file1")


async def test_blob_iteration(async_db_mem: AsyncBeaverDB):
    """Test keys and items iteration."""
    b = async_db_mem.blob("assets")
    await b.put("a", b"1")
    await b.put("b", b"2")

    keys = []
    async for k in b:
        keys.append(k)
    assert sorted(keys) == ["a", "b"]

    items = {}
    async for k, v in b.items():
        items[k] = v
    assert items == {"a": b"1", "b": b"2"}


async def test_blob_type_validation(async_db_mem: AsyncBeaverDB):
    """Ensure we can't store strings/ints as blobs."""
    b = async_db_mem.blob("strict")

    with pytest.raises(TypeError):
        await b.put("text_file", "I am a string, not bytes")

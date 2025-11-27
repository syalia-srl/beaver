import asyncio
import pytest
from beaver import AsyncBeaverDB

# Run all tests with the async loop
pytestmark = pytest.mark.asyncio


async def test_list_push_pop(async_db_mem: AsyncBeaverDB):
    """Test standard Stack (LIFO) behavior."""
    l = async_db_mem.list("stack")

    # Push items
    await l.push("bottom")
    await l.push("top")

    assert await l.count() == 2

    # Pop (Last-In, First-Out)
    assert await l.pop() == "top"
    assert await l.pop() == "bottom"
    assert await l.pop() is None
    assert await l.count() == 0


async def test_list_prepend_deque(async_db_mem: AsyncBeaverDB):
    """Test standard Queue (FIFO) behavior."""
    l = async_db_mem.list("queue")

    # Prepend items
    await l.prepend("first")
    await l.prepend("second")
    # List order is now: ["second", "first"]

    assert await l.count() == 2

    # Deque (Remove from start)
    assert await l.deque() == "second"
    assert await l.deque() == "first"
    assert await l.deque() is None


async def test_list_get_set_delete(async_db_mem: AsyncBeaverDB):
    """Test index-based random access and modification."""
    l = async_db_mem.list("items")
    await l.push("a")
    await l.push("b")
    await l.push("c")

    # Get by index
    assert await l.get(0) == "a"
    assert await l.get(1) == "b"
    assert await l.get(-1) == "c"

    # Set by index
    await l.set(1, "updated_b")
    assert await l.get(1) == "updated_b"

    # Delete by index
    await l.delete(1)  # Removes "updated_b"
    # List is now ["a", "c"]

    assert await l.count() == 2
    assert await l.get(1) == "c"

    # Verify index out of bounds
    with pytest.raises(IndexError):
        await l.get(99)


async def test_list_slicing(async_db_mem: AsyncBeaverDB):
    """Test retrieving slices of the list."""
    l = async_db_mem.list("slice_test")
    for i in range(5):
        await l.push(i)

    # List: [0, 1, 2, 3, 4]

    # Standard slice [1:4] -> [1, 2, 3]
    assert await l.get(slice(1, 4)) == [1, 2, 3]

    # Start only [2:] -> [2, 3, 4]
    assert await l.get(slice(2, None)) == [2, 3, 4]

    # Stop only [:2] -> [0, 1]
    assert await l.get(slice(None, 2)) == [0, 1]


async def test_list_insert(async_db_mem: AsyncBeaverDB):
    """Test inserting items at arbitrary positions."""
    l = async_db_mem.list("insertion")
    await l.push("start")
    await l.push("end")

    # Insert in the middle (index 1)
    await l.insert(1, "middle")

    assert await l.get(0) == "start"
    assert await l.get(1) == "middle"
    assert await l.get(2) == "end"

    # Insert at start (index 0)
    await l.insert(0, "prefix")
    assert await l.get(0) == "prefix"

    # Insert at end (index 4)
    await l.insert(4, "suffix")
    assert await l.get(4) == "suffix"


async def test_list_iteration(async_db_mem: AsyncBeaverDB):
    """Test async iteration logic."""
    l = async_db_mem.list("iter")
    items = ["x", "y", "z"]
    for item in items:
        await l.push(item)

    collected = []
    async for item in l:
        collected.append(item)

    assert collected == items


async def test_list_contains(async_db_mem: AsyncBeaverDB):
    """Test item existence check."""
    l = async_db_mem.list("membership")
    await l.push("needle")

    assert await l.contains("needle") is True
    assert await l.contains("haystack") is False


async def test_list_clear(async_db_mem: AsyncBeaverDB):
    """Test clearing the list."""
    l = async_db_mem.list("trash")
    await l.push(1)
    await l.push(2)

    await l.clear()
    assert await l.count() == 0


async def test_list_dump(async_db_mem: AsyncBeaverDB):
    """Test serializing list to dict."""
    l = async_db_mem.list("dumper")
    await l.push("data")

    dump = await l.dump()
    assert dump["metadata"]["name"] == "dumper"
    assert dump["metadata"]["count"] == 1
    assert dump["items"] == ["data"]

import asyncio
import pytest
from beaver import AsyncBeaverDB

pytestmark = pytest.mark.asyncio


async def test_queue_priority(async_db_mem: AsyncBeaverDB):
    """Test that items are retrieved in priority order."""
    q = async_db_mem.queue("prio_test")

    await q.put("mid", priority=10)
    await q.put("low", priority=20)
    await q.put("high", priority=1)

    # Expect: 1 (high), 10 (mid), 20 (low)

    i1 = await q.get()
    assert i1.data == "high"
    assert i1.priority == 1.0

    i2 = await q.get()
    assert i2.data == "mid"
    assert i2.priority == 10.0

    i3 = await q.get()
    assert i3.data == "low"

    assert await q.count() == 0


async def test_queue_fifo(async_db_mem: AsyncBeaverDB):
    """Test FIFO behavior for items with same priority."""
    q = async_db_mem.queue("fifo_test")

    await q.put("first", priority=1)
    await asyncio.sleep(0.01)  # Ensure timestamp diff
    await q.put("second", priority=1)

    i1 = await q.get()
    assert i1.data == "first"

    i2 = await q.get()
    assert i2.data == "second"


async def test_queue_peek(async_db_mem: AsyncBeaverDB):
    """Test peek does not remove items."""
    q = async_db_mem.queue("peek_test")
    await q.put("data", 1)

    p = await q.peek()
    assert p.data == "data"
    assert await q.count() == 1

    g = await q.get()
    assert g.data == "data"
    assert await q.count() == 0


async def test_queue_get_nonblocking(async_db_mem: AsyncBeaverDB):
    """Test non-blocking get on empty queue."""
    q = async_db_mem.queue("empty")

    with pytest.raises(IndexError):
        await q.get(block=False)


async def test_queue_get_blocking_timeout(async_db_mem: AsyncBeaverDB):
    """Test blocking get times out."""
    q = async_db_mem.queue("timeout_test")

    with pytest.raises(TimeoutError):
        await q.get(block=True, timeout=0.1)


async def test_queue_producer_consumer(async_db_mem: AsyncBeaverDB):
    """Test a producer task feeding a blocking consumer task."""
    q = async_db_mem.queue("pc_test")

    async def consumer():
        # This will block until producer puts something
        return await q.get(block=True, timeout=1.0)

    async def producer():
        await asyncio.sleep(0.1)
        await q.put("delivered", 1)

    task_c = asyncio.create_task(consumer())
    task_p = asyncio.create_task(producer())

    results = await asyncio.gather(task_c, task_p)
    item = results[0]

    assert item.data == "delivered"


async def test_queue_iteration(async_db_mem: AsyncBeaverDB):
    """Test async iteration."""
    q = async_db_mem.queue("iter")
    await q.put("a", 1)
    await q.put("b", 2)

    items = []
    async for item in q:
        items.append(item.data)

    assert items == ["a", "b"]


async def test_queue_clear(async_db_mem: AsyncBeaverDB):
    """Test clearing the queue."""
    q = async_db_mem.queue("trash")
    await q.put("a", 1)
    await q.clear()
    assert await q.count() == 0

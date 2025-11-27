import asyncio
import pytest
import time
from beaver import AsyncBeaverDB

pytestmark = pytest.mark.asyncio


async def test_log_append_range(async_db_mem: AsyncBeaverDB):
    """Test basic logging and range retrieval."""
    log = async_db_mem.log("syslog")

    # 1. Log data
    await log.log("start")
    start_time = time.time()
    await asyncio.sleep(0.01)

    await log.log("middle")
    await asyncio.sleep(0.01)
    end_time = time.time()

    await log.log("end")

    # 2. Verify Count
    assert await log.count() == 3

    # 3. Test Range (All)
    all_logs = await log.range()
    assert len(all_logs) == 3
    assert all_logs[0].data == "start"
    assert all_logs[2].data == "end"

    # 4. Test Range (Time bounded)
    middle_logs = await log.range(start=start_time, end=end_time)
    assert len(middle_logs) == 1
    assert middle_logs[0].data == "middle"

    # 5. Test Limit
    limit_logs = await log.range(limit=2)
    assert len(limit_logs) == 2
    assert limit_logs[0].data == "start"
    assert limit_logs[1].data == "middle"


async def test_log_collision_handling(async_db_mem: AsyncBeaverDB):
    """Test that rapid inserts don't crash on PK constraint."""
    log = async_db_mem.log("rapid")

    # Insert 100 items as fast as possible
    # This should trigger the IntegrityError retry logic
    for i in range(100):
        await log.log(f"msg_{i}")

    assert await log.count() == 100

    # Verify strict ordering is preserved (timestamps should be unique)
    entries = await log.range()
    timestamps = [e.timestamp for e in entries]
    assert len(timestamps) == len(set(timestamps))  # All unique
    assert timestamps == sorted(timestamps)  # Monotonic


async def test_log_live_tailing(async_db_mem: AsyncBeaverDB):
    """Test the live() async generator."""
    log = async_db_mem.log("live_feed")

    # 1. Start a consumer task
    received = []

    async def consumer():
        async for entry in log.live(poll_interval=0.01):
            received.append(entry.data)
            if len(received) >= 2:
                break

    task = asyncio.create_task(consumer())

    # 2. Producer
    await asyncio.sleep(0.05)  # Wait for consumer to establish baseline
    await log.log("msg1")
    await asyncio.sleep(0.05)
    await log.log("msg2")

    # 3. Wait for consumer
    await asyncio.wait_for(task, timeout=1.0)

    assert received == ["msg1", "msg2"]


async def test_log_clear(async_db_mem: AsyncBeaverDB):
    """Test clearing the log."""
    log = async_db_mem.log("trash")
    await log.log("a")
    await log.clear()
    assert await log.count() == 0

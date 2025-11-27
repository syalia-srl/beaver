import asyncio
import pytest
from beaver import AsyncBeaverDB

pytestmark = pytest.mark.asyncio

async def test_sketch_add_contains(async_db_mem: AsyncBeaverDB):
    """Test basic membership (Bloom Filter)."""
    # Small capacity for easy testing
    s = async_db_mem.sketch("bloom", capacity=1000, error_rate=0.01)

    await s.add("apple")
    await s.add("banana")

    assert await s.contains("apple") is True
    assert await s.contains("banana") is True
    assert await s.contains("cherry") is False

async def test_sketch_cardinality(async_db_mem: AsyncBeaverDB):
    """Test cardinality estimation (HLL)."""
    s = async_db_mem.sketch("counter", capacity=10000)

    # Add unique items
    async with s.batched() as batch:
        for i in range(1000):
            batch.add(f"item_{i}")

    count = await s.count()
    # HLL is approximate, usually within small % error
    assert 950 < count < 1050

async def test_sketch_batched(async_db_mem: AsyncBeaverDB):
    """Test batched updates."""
    s = async_db_mem.sketch("batch_test")

    async with s.batched() as batch:
        for i in range(100):
            batch.add(i)

    assert await s.count() > 90 # Approx check
    assert await s.contains(0) is True
    assert await s.contains(99) is True

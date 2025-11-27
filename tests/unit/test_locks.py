import asyncio
import pytest
import time
from beaver import AsyncBeaverDB

pytestmark = pytest.mark.asyncio


async def test_lock_acquire_release(async_db_mem: AsyncBeaverDB):
    """Test basic acquire and release mechanics."""
    lock = async_db_mem.lock("test_lock")

    assert await lock.acquire() is True
    assert lock._acquired is True

    await lock.release()
    assert lock._acquired is False


async def test_lock_mutual_exclusion(async_db_mem: AsyncBeaverDB):
    """Test that two instances cannot hold the same lock."""
    lock1 = async_db_mem.lock("mutex")
    lock2 = async_db_mem.lock("mutex")

    # 1. First lock acquires
    assert await lock1.acquire() is True

    # 2. Second lock fails (non-blocking)
    assert await lock2.acquire(block=False) is False

    # 3. First releases
    await lock1.release()

    # 4. Second acquires
    assert await lock2.acquire() is True
    await lock2.release()


async def test_lock_context_manager(async_db_mem: AsyncBeaverDB):
    """Test the async context manager protocol."""
    async with async_db_mem.lock("ctx_lock") as lock:
        assert lock._acquired is True
        # Try to acquire same lock with another instance
        lock2 = async_db_mem.lock("ctx_lock")
        assert await lock2.acquire(block=False) is False

    # Lock should be released automatically on exit
    assert await lock2.acquire(block=False) is True


async def test_lock_ttl_expiry(async_db_mem: AsyncBeaverDB):
    """Test that crashed/stale locks are cleaned up after TTL."""
    # 1. Acquire with very short TTL
    lock1 = async_db_mem.lock("ttl_lock", lock_ttl=0.1)
    await lock1.acquire()

    # 2. Wait for TTL to expire (simulate crash/hang)
    await asyncio.sleep(0.2)

    # 3. New lock should be able to 'steal' it
    lock2 = async_db_mem.lock("ttl_lock")
    assert await lock2.acquire(block=False) is True


async def test_lock_renew(async_db_mem: AsyncBeaverDB):
    """Test heartbeat mechanism."""
    lock = async_db_mem.lock("renew_lock", lock_ttl=0.1)
    await lock.acquire()

    # Renew the lock (extend TTL)
    assert await lock.renew(lock_ttl=1.0) is True

    # Sleep past original TTL
    await asyncio.sleep(0.2)

    # Should still hold it (lock2 fails)
    lock2 = async_db_mem.lock("renew_lock")
    assert await lock2.acquire(block=False) is False


async def test_lock_wait_timeout(async_db_mem: AsyncBeaverDB):
    """Test that acquire times out correctly."""
    lock1 = async_db_mem.lock("timeout_lock")
    await lock1.acquire()

    lock2 = async_db_mem.lock("timeout_lock")
    start = time.time()

    # Try to acquire for 0.2s
    success = await lock2.acquire(timeout=0.2)
    duration = time.time() - start

    assert success is False
    assert duration >= 0.2


async def test_lock_fairness(async_db_mem: AsyncBeaverDB):
    """Test FIFO ordering of waiters."""
    lock = async_db_mem.lock("fair_lock")
    await lock.acquire()

    results = []

    async def worker(n):
        l = async_db_mem.lock("fair_lock")
        await l.acquire()
        results.append(n)
        await l.release()

    # Start tasks in order: 1, 2, 3
    t1 = asyncio.create_task(worker(1))
    await asyncio.sleep(0.01)  # Ensure insert order in DB
    t2 = asyncio.create_task(worker(2))
    await asyncio.sleep(0.01)
    t3 = asyncio.create_task(worker(3))

    # Release main lock, unleashing the workers
    await lock.release()

    await asyncio.gather(t1, t2, t3)

    # Must be strictly 1 -> 2 -> 3
    assert results == [1, 2, 3]


async def test_lock_clear(async_db_mem: AsyncBeaverDB):
    """Test administrative clear."""
    lock1 = async_db_mem.lock("stuck_lock")
    await lock1.acquire()

    lock2 = async_db_mem.lock("stuck_lock")
    assert await lock2.clear() is True

    # Lock1 thinks it has it, but it's gone from DB
    # Lock2 can now acquire
    assert await lock2.acquire(block=False) is True

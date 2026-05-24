"""Integration tests for the fracdex-based list ordering.

These tests exercise AsyncBeaverList through the public API to confirm
the bug-hunt finding from 2026-05-24 is fixed and that the new ordering
behaves correctly under random workloads.
"""

import random

import pytest

from beaver import AsyncBeaverDB

pytestmark = pytest.mark.asyncio


async def test_insert_at_contended_index_does_not_crash(async_db_mem: AsyncBeaverDB):
    """The original bug: insert(1, ...) crashed at ~52 calls under the
    float-midpoint scheme. With fracdex it must survive 1000+."""
    lst = async_db_mem.list("contended")
    await lst.push("first")
    await lst.push("last")
    for i in range(1000):
        await lst.insert(1, f"v{i}")
    assert await lst.count() == 1002
    assert await lst.get(0) == "first"
    assert await lst.get(-1) == "last"


async def test_insert_preserves_strict_ordering(async_db_mem: AsyncBeaverDB):
    """After many inserts, iterating the list returns items in the order
    they would be in if the list were maintained in-memory."""
    lst = async_db_mem.list("ordering")
    await lst.push("a")
    await lst.push("z")
    for i in range(100):
        await lst.insert(1, f"{i:02d}")
    expected = ["a"] + [f"{i:02d}" for i in reversed(range(100))] + ["z"]
    actual = [item async for item in lst]
    assert actual == expected


async def test_fuzz_against_python_list_oracle(async_db_mem: AsyncBeaverDB):
    """Random sequence of push/prepend/insert/pop/deque/get operations.
    The in-memory Python list is the oracle; the persisted list must match
    after every operation."""
    rng = random.Random(0xC0DE)
    lst = async_db_mem.list("fuzz")
    oracle: list[str] = []

    ops = ["push", "prepend", "insert", "pop", "deque"]
    for step in range(1000):
        op = rng.choice(ops)
        if op == "push":
            v = f"v{step}"
            await lst.push(v)
            oracle.append(v)
        elif op == "prepend":
            v = f"v{step}"
            await lst.prepend(v)
            oracle.insert(0, v)
        elif op == "insert":
            if len(oracle) == 0:
                continue
            i = rng.randint(0, len(oracle))
            v = f"v{step}"
            await lst.insert(i, v)
            oracle.insert(i, v)
        elif op == "pop":
            persisted = await lst.pop()
            expected = oracle.pop() if oracle else None
            assert persisted == expected, f"step {step} op {op}"
        elif op == "deque":
            persisted = await lst.deque()
            expected = oracle.pop(0) if oracle else None
            assert persisted == expected, f"step {step} op {op}"

        if step % 50 == 0:
            actual = [item async for item in lst]
            assert actual == oracle, f"divergence at step {step}: {actual} != {oracle}"

    actual = [item async for item in lst]
    assert actual == oracle
    assert await lst.count() == len(oracle)

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

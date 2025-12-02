import pytest
import numpy as np
import os
from beaver.core import AsyncBeaverDB


pytestmark = pytest.mark.asyncio


async def test_lsh_search_correctness(async_db_mem: AsyncBeaverDB):
    """
    Verifies that LSH search correctly identifies nearest neighbors
    in a simple scenario with distinct clusters.
    """
    vectors = async_db_mem.vectors("sanity_check")
    dim = 64

    # 1. Create two distinct reference vectors (Cluster Centers)
    # Vec A: Positive quadrant
    vec_a = np.ones(dim, dtype=np.float32)
    vec_a /= np.linalg.norm(vec_a)

    # Vec B: Negative quadrant (Opposite)
    vec_b = -np.ones(dim, dtype=np.float32)
    vec_b /= np.linalg.norm(vec_b)

    # Insert them
    await vectors.set("item_a", vec_a.tolist())
    await vectors.set("item_b", vec_b.tolist())

    # 2. Query with a vector very close to A (Add slight noise)
    query_a = vec_a + np.random.normal(0, 0.05, dim)

    # Force "lsh" method to bypass the linear scan threshold check
    results_lsh = await vectors.near(query_a.tolist(), k=1, method="lsh")

    assert len(results_lsh) > 0
    assert (
        results_lsh[0].id == "item_a"
    ), "LSH failed to find the obvious neighbor item_a"

    # Verify against exact linear scan
    results_exact = await vectors.near(query_a.tolist(), k=1, method="exact")
    assert results_exact[0].id == "item_a"

    # 3. Query close to B
    query_b = vec_b + np.random.normal(0, 0.05, dim)

    results_lsh_b = await vectors.near(query_b.tolist(), k=1, method="lsh")
    assert len(results_lsh_b) > 0
    assert (
        results_lsh_b[0].id == "item_b"
    ), "LSH failed to find the obvious neighbor item_b"


async def test_lsh_update_consistency(async_db_mem: AsyncBeaverDB):
    """
    Verifies that updating a vector moves it to the correct new bucket
    (or updates the existing entry) and finding duplicates works.
    """
    vectors = async_db_mem.vectors("consistency_check")
    dim = 32

    # Vector 1
    v1 = np.zeros(dim, dtype=np.float32)
    v1[0] = 1.0  # Points along X axis

    # Vector 2 (Orthogonal to V1)
    v2 = np.zeros(dim, dtype=np.float32)
    v2[1] = 1.0  # Points along Y axis

    # 1. Insert ID "obj1" as v1
    await vectors.set("obj1", v1.tolist())

    # Search near v1 should find obj1
    res = await vectors.near(v1.tolist(), k=1, method="lsh")
    assert res[0].id == "obj1"

    # 2. Update ID "obj1" to be v2
    await vectors.set("obj1", v2.tolist())

    # Search near v1 should NOT find obj1 (or score very low)
    # Search near v2 SHOULD find obj1
    res_v2 = await vectors.near(v2.tolist(), k=1, method="lsh")
    assert res_v2[0].id == "obj1"
    assert res_v2[0].score <= 0.01  # Should be near 0.0 distance


async def test_lsh_auto_fallback(async_db_mem: AsyncBeaverDB):
    """
    Verifies that 'auto' method works (sanity check that it runs without crashing).
    It will likely use linear scan because N is small, but we check the flow.
    """
    vectors = async_db_mem.vectors("auto_check")
    dim = 16

    # Insert a few vectors
    for i in range(10):
        v = np.random.rand(dim).tolist()
        await vectors.set(f"id_{i}", v)

    query = np.random.rand(dim).tolist()

    # Should default to Linear Scan internally because count < 10,000
    results = await vectors.near(query, k=3, method="auto")

    assert len(results) == 3

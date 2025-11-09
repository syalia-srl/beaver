import pytest

pytest.mark.integration

from beaver import BeaverDB


def test_dict_cache(db_cached: BeaverDB):
    d = db_cached.dict("test")

    # Add an item and verify it hits the cache
    d["k"] = 5
    _ = d["k"]

    assert d.cache.stats().hits == 1
    assert d.cache.stats().misses == 0

    # Delete the item and verify the cache is empty
    del d["k"]
    assert d.cache.stats().pops == 1

    # Verify after deletion it's no longer in the cache
    with pytest.raises(KeyError):
        _ = d["k"]

    assert d.cache.stats().misses == 1

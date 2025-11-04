import pytest
pytest.mark.integration

from beaver import BeaverDB

def test_dict_cache(db: BeaverDB):
    d = db.dict("test")
    d["k"] = 5
    _ = d["k"]
    assert db.cache.stats().hits == 1
    del d["k"]
    assert db.cache.stats().pops == 1
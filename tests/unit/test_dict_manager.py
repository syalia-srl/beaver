import time
import pytest
from beaver import BeaverDB, Model

# --- Test Model for Serialization ---

class Person(Model):
    name: str
    age: int

# --- Test Cases ---

def test_dict_set_and_get(db: BeaverDB):
    """Tests basic __setitem__ and __getitem__."""
    config = db.dict("config")

    config["theme"] = "dark"
    config["user_id"] = 123
    config["features"] = {"beta": True, "new_nav": False}

    assert config["theme"] == "dark"
    assert config["user_id"] == 123
    assert config["features"] == {"beta": True, "new_nav": False}

def test_dict_get_with_default(db: BeaverDB):
    """Tests the .get() method with a default value."""
    config = db.dict("config")

    config["existing_key"] = "hello"

    assert config.get("existing_key", "default") == "hello"
    assert config.get("missing_key", "default") == "default"
    assert config.get("missing_key") is None

def test_dict_delete_item(db: BeaverDB):
    """Tests __delitem__ and that it raises KeyError."""
    config = db.dict("config")

    config["key_to_delete"] = "some_value"
    assert config.get("key_to_delete") == "some_value"

    del config["key_to_delete"]
    assert config.get("key_to_delete") is None

    # Test that deleting a non-existent key raises KeyError
    with pytest.raises(KeyError):
        del config["non_existent_key"]

def test_dict_get_missing_key(db: BeaverDB):
    """Tests that __getitem__ raises KeyError for missing keys."""
    config = db.dict("config")

    with pytest.raises(KeyError):
        _ = config["non_existent_key"]

def test_dict_len(db: BeaverDB):
    """Tests the __len__ method."""
    config = db.dict("config")
    assert len(config) == 0

    config["key1"] = 1
    assert len(config) == 1

    config["key2"] = 2
    assert len(config) == 2

    config["key1"] = "overwrite" # Overwriting should not change length
    assert len(config) == 2

    del config["key1"]
    assert len(config) == 1

def test_dict_ttl_expiry(db: BeaverDB):
    """Tests that keys set with a TTL expire correctly."""
    cache = db.dict("cache")

    # Set a key with a 1-second TTL
    cache.set("short_lived", "data", ttl_seconds=1)

    # It should exist immediately
    assert cache.get("short_lived") == "data"

    # Wait for it to expire
    time.sleep(1.1)

    # .get() should now return None
    assert cache.get("short_lived") is None

    # __getitem__ should raise KeyError
    with pytest.raises(KeyError):
        _ = cache["short_lived"]

def test_dict_ttl_value_error(db: BeaverDB):
    """Tests that invalid TTL values raise an error."""
    cache = db.dict("cache")
    with pytest.raises(ValueError):
        cache.set("key", "value", ttl_seconds=0)
    with pytest.raises(ValueError):
        cache.set("key", "value", ttl_seconds=-10)

def test_dict_iterators(db: BeaverDB):
    """Tests keys(), values(), and items() iterators."""
    config = db.dict("config")

    config["a"] = 1
    config["b"] = 2

    keys = list(config.keys())
    assert len(keys) == 2
    assert "a" in keys
    assert "b" in keys

    values = list(config.values())
    assert len(values) == 2
    assert 1 in values
    assert 2 in values

    items = list(config.items())
    assert len(items) == 2
    assert ("a", 1) in items
    assert ("b", 2) in items

    # Test __iter__ (should be keys)
    iter_keys = list(config)
    assert sorted(iter_keys) == sorted(["a", "b"])

def test_dict_pop(db: BeaverDB):
    """Tests the .pop() method."""
    config = db.dict("config")

    config["a"] = 1

    assert config.pop("a") == 1
    assert len(config) == 0
    assert config.get("a") is None

    # Test pop with default
    assert config.pop("b", "default") == "default"

    # Test pop on missing key (no default)
    assert config.pop("c") is None

def test_dict_contains(db: BeaverDB):
    """Tests the __contains__ (in) operator."""
    config = db.dict("config")

    config["a"] = 1

    assert "a" in config
    assert "b" not in config

def test_dict_with_model_serialization(db: BeaverDB):
    """Tests that the DictManager correctly serializes/deserializes models."""
    users = db.dict("users", model=Person)

    alice = Person(name="Alice", age=30)
    users["alice"] = alice

    # Retrieve the object
    retrieved_user = users["alice"]

    assert isinstance(retrieved_user, Person)
    assert retrieved_user.name == "Alice"
    assert retrieved_user.age == 30

def test_dict_dump(db: BeaverDB):
    """Tests the .dump() method."""
    config = db.dict("dump_test")
    config["key1"] = "value1"
    config["key2"] = {"nested": True}

    dump_data = config.dump()

    assert dump_data["metadata"]["type"] == "Dict"
    assert dump_data["metadata"]["name"] == "dump_test"
    assert dump_data["metadata"]["count"] == 2

    items = dump_data["items"]
    assert len(items) == 2
    assert {"key": "key1", "value": "value1"} in items
    assert {"key": "key2", "value": {"nested": True}} in items

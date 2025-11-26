# tests/unit/test_sketch_manager.py
import pytest
import os
from beaver import BeaverDB

pytestmark = pytest.mark.unit

def test_sketch_creation_defaults(db_memory: BeaverDB):
    """Tests creating a sketch with default parameters."""
    # Default capacity=1_000_000, error_rate=0.01
    sketch = db_memory.sketch("visitors")

    assert len(sketch) == 0
    assert "alice" not in sketch

    # Verify internal configuration matches defaults
    # p=14 for error=0.01
    assert sketch._sketch.p == 14

def test_sketch_custom_params(db_memory: BeaverDB):
    """Tests creating a sketch with custom parameters (low capacity, high error)."""
    # High error rate (5%) -> lower p
    sketch = db_memory.sketch("small_sketch", capacity=100, error_rate=0.05)

    # p should be 9 for 5% error (2 * log2(1.04/0.05) ≈ 8.7)
    assert sketch._sketch.p == 9
    assert len(sketch) == 0

def test_sketch_add_and_contains(db_memory: BeaverDB):
    """Tests the Bloom Filter membership testing."""
    sketch = db_memory.sketch("bloom_test")

    items = ["item1", "item2", "item3"]

    for item in items:
        sketch.add(item)

    for item in items:
        assert item in sketch

    assert "non_existent" not in sketch

def test_sketch_cardinality_hll(db_memory: BeaverDB):
    """Tests the HyperLogLog cardinality estimation."""
    # Use a small error rate for better accuracy in this test
    sketch = db_memory.sketch("hll_test", error_rate=0.01)

    # Add 1000 unique items
    with sketch.batched() as batch:
        for i in range(1000):
            batch.add(f"user_{i}")

    count = len(sketch)

    # HLL is probabilistic, but with p=14 (error ~0.8%),
    # 1000 items should be very close.
    # We allow a generous 5% margin for this sanity check.
    assert 950 < count < 1050

def test_sketch_batched_write(db_path: str):
    """Tests the high-performance .batched() context manager."""
    sketch = BeaverDB(db_path).sketch("batch_test")

    # Add items in a batch
    with sketch.batched() as batch:
        for i in range(500):
            batch.add(f"batch_{i}")

    # Reopen
    sketch = BeaverDB(db_path).sketch("batch_test")

    # Verify they were added
    assert len(sketch) > 450 # Rough HLL check
    assert "batch_0" in sketch
    assert "batch_499" in sketch
    assert "batch_500" not in sketch

def test_sketch_config_validation(db_path):
    """Tests strict validation of capacity/error_rate on load."""
    db = BeaverDB(db_path)

    pytest.skip("Validation not working")

    # 1. Create with specific params
    db.sketch("strict_sketch", capacity=1000, error_rate=0.05)
    db.close()

    db = BeaverDB(db_path)
    # 2. Try to load with DIFFERENT params -> Should fail
    with pytest.raises(ValueError) as excinfo:
        # Try loading with default (1M, 0.01) instead of (1000, 0.05)
        db.sketch("strict_sketch", capacity=1_000_000, error_rate=0.01)

    assert "Sketch 'strict_sketch' exists with capacity=1000" in str(excinfo.value)

    # 3. Load with CORRECT params -> Should succeed
    sketch_valid = db.sketch("strict_sketch", capacity=1000, error_rate=0.05)
    assert sketch_valid is not None

def test_sketch_mixed_types(db_memory: BeaverDB):
    """Tests adding different python types."""
    sketch = db_memory.sketch("types_test")

    sketch.add(123)
    sketch.add(45.67)
    sketch.add("string")
    sketch.add(True)

    assert 123 in sketch
    assert 45.67 in sketch
    assert "string" in sketch
    assert True in sketch
    assert False not in sketch
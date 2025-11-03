import pytest
import time
from datetime import datetime, timedelta, timezone
from beaver import BeaverDB, Model

pytestmark = pytest.mark.unit

# --- Test Model for Serialization ---
class LogEntry(Model):
    level: str
    message: str

# --- Helper to create timestamps ---
def ts(seconds_offset: float) -> datetime:
    """Helper to create a precise, offset timestamp."""
    # Using timezone.utc to be explicit, as logs.py does
    return datetime.now(timezone.utc) + timedelta(seconds=seconds_offset)

# --- Test Cases ---

def test_log_log_and_range(db_memory: BeaverDB):
    """Tests logging a single entry and retrieving it with range()."""
    logs = db_memory.log("test_log_range")

    t1 = ts(-1)
    t2 = ts(1)

    log_data = {"event": "start", "value": 1}
    logs.log(log_data)

    # Range should include the log entry
    results = logs.range(t1, t2)
    assert len(results) == 1
    assert results[0] == log_data

def test_log_range_precision(db_memory: BeaverDB):
    """Tests logging multiple entries and retrieving a precise subset."""
    logs = db_memory.log("test_log_precision")

    t_start = ts(0)
    t_mid = ts(0.02)
    t_end = ts(0.04)

    time.sleep(0.01)
    logs.log({"id": 1}) # Should be included
    time.sleep(0.02)
    logs.log({"id": 2}) # Should be included
    time.sleep(0.05)
    logs.log({"id": 3}) # Should NOT be included

    # Query the range from start to end
    results = logs.range(t_start, t_end)

    assert len(results) == 2
    assert results[0] == {"id": 1}
    assert results[1] == {"id": 2}

def test_log_range_empty(db_memory: BeaverDB):
    """Tests that range() returns an empty list for no matches."""
    logs = db_memory.log("test_log_empty")
    logs.log({"id": 1}, timestamp=ts(0))

    # Query a time range in the future
    results = logs.range(ts(1), ts(2))
    assert len(results) == 0

def test_log_with_model_serialization(db_memory: BeaverDB):
    """Tests that LogManager correctly serializes/deserializes models."""
    logs = db_memory.log("test_log_model", model=LogEntry)

    entry = LogEntry(level="INFO", message="System start")

    t1 = ts(-1)
    logs.log(entry)
    t2 = ts(1)

    results = logs.range(t1, t2)

    assert len(results) == 1
    retrieved = results[0]

    assert isinstance(retrieved, LogEntry)
    assert retrieved.level == "INFO"
    assert retrieved.message == "System start"

def test_log_iter(db_memory: BeaverDB):
    """Tests that __iter__ yields all log entries in chronological order."""
    logs = db_memory.log("test_log_iter")

    logs.log({"id": 2}, timestamp=ts(0.02))
    logs.log({"id": 1}, timestamp=ts(0.01)) # Log out of order
    logs.log({"id": 3}, timestamp=ts(0.03))

    # The iterator should return them in correct timestamp order
    results = list(logs) # Calls __iter__

    assert len(results) == 3
    # Each item is a (timestamp, data) tuple
    assert results[0][1] == {"id": 1}
    assert results[1][1] == {"id": 2}
    assert results[2][1] == {"id": 3}

def test_log_dump(db_memory: BeaverDB):
    """Tests the .dump() method."""
    logs = db_memory.log("test_log_dump")

    t1 = ts(0.01)
    t2 = ts(0.02)
    logs.log({"id": 1}, timestamp=t1)
    logs.log({"id": 2}, timestamp=t2)

    dump_data = logs.dump()

    assert dump_data["metadata"]["type"] == "Log"
    assert dump_data["metadata"]["name"] == "test_log_dump"
    assert dump_data["metadata"]["count"] == 2

    items = dump_data["items"]
    assert len(items) == 2

    # Check items are correct and in order
    assert items[0]["data"] == {"id": 1}
    assert items[0]["timestamp"] == t1.timestamp()

    assert items[1]["data"] == {"id": 2}
    assert items[1]["timestamp"] == t2.timestamp()

def test_log_dump_with_model(db_memory: BeaverDB):
    """Tests that .dump() correctly serializes model instances."""
    logs = db_memory.log("test_log_dump_model", model=LogEntry)
    t1 = ts(0.01)
    logs.log(LogEntry(level="INFO", message="Test"), timestamp=t1)

    dump_data = logs.dump()

    assert dump_data["metadata"]["count"] == 1
    item = dump_data["items"][0]

    # Ensure data is a dict (JSON-serialized), not a LogEntry object
    assert item["data"] == {"level": "INFO", "message": "Test"}
    assert item["timestamp"] == t1.timestamp()
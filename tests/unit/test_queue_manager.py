from pydantic import BaseModel
import pytest
import time
from beaver import BeaverDB
from beaver.queues import QueueItem

pytestmark = pytest.mark.unit

# --- Test Model for Serialization ---
class Task(BaseModel):
    action: str
    task_id: int

# --- Test Cases ---

# 1. Basic Operations

def test_queue_put_and_len(db_memory: BeaverDB):
    """Tests basic put and __len__."""
    queue = db_memory.queue("test_put_len")
    assert len(queue) == 0

    queue.put("task-1", priority=10)
    queue.put("task-2", priority=1)

    assert len(queue) == 2

def test_queue_get_non_blocking_empty(db_memory: BeaverDB):
    """Tests that get(block=False) on an empty queue raises IndexError."""
    queue = db_memory.queue("test_get_empty")
    assert len(queue) == 0

    with pytest.raises(IndexError):
        queue.get(block=False)

def test_queue_peek_empty(db_memory: BeaverDB):
    """Tests that peek() on an empty queue returns None."""
    queue = db_memory.queue("test_peek_empty")
    assert len(queue) == 0
    assert queue.peek() is None

# 2. Priority and FIFO Ordering

def test_queue_priority_ordering(db_memory: BeaverDB):
    """Tests that get() retrieves items in priority order (lower number first)."""
    queue = db_memory.queue("test_priority")

    # Put items out of order
    queue.put("task-medium", priority=10)
    queue.put("task-low", priority=20)
    queue.put("task-high", priority=1)

    assert len(queue) == 3

    # Items should be retrieved in priority order
    item1 = queue.get(block=False)
    assert item1.data == "task-high"
    assert item1.priority == 1

    item2 = queue.get(block=False)
    assert item2.data == "task-medium"
    assert item2.priority == 10

    item3 = queue.get(block=False)
    assert item3.data == "task-low"
    assert item3.priority == 20

    assert len(queue) == 0

def test_queue_fifo_ordering_for_same_priority(db_memory: BeaverDB):
    """Tests that items with the same priority are retrieved in FIFO order."""
    queue = db_memory.queue("test_fifo")

    queue.put("task-a", priority=5)
    # Ensure a different timestamp by sleeping briefly
    time.sleep(0.01)
    queue.put("task-b", priority=5)
    time.sleep(0.01)
    queue.put("task-c", priority=1) # This should come out first

    # First get the high-priority item
    item_c = queue.get(block=False)
    assert item_c.data == "task-c"

    # Next items should be FIFO for priority 5
    item_a = queue.get(block=False)
    assert item_a.data == "task-a"

    item_b = queue.get(block=False)
    assert item_b.data == "task-b"

    assert len(queue) == 0

def test_queue_peek(db_memory: BeaverDB):
    """Tests that peek() returns the highest-priority item without removing it."""
    queue = db_memory.queue("test_peek")

    queue.put("task-low", priority=10)
    queue.put("task-high", priority=1)

    assert len(queue) == 2

    # Peek should show task-high
    item = queue.peek()
    assert item is not None
    assert item.data == "task-high"
    assert item.priority == 1

    # Length should still be 2
    assert len(queue) == 2

    # Get should return the same item
    item_get = queue.get(block=False)
    assert item_get.data == "task-high"

    # Length should now be 1
    assert len(queue) == 1

# 3. Blocking Operations

def test_queue_blocking_get_timeout(db_memory: BeaverDB):
    """Tests that get(block=True, timeout=...) raises TimeoutError."""
    queue = db_memory.queue("test_timeout")

    start_time = time.time()
    with pytest.raises(TimeoutError):
        queue.get(block=True, timeout=0.1)
    end_time = time.time()

    # Check that it actually waited for at least the timeout duration
    assert (end_time - start_time) >= 0.1

# 4. Advanced Features (Serialization & Dump)

def test_queue_with_model_serialization(db_memory: BeaverDB):
    """Tests that the QueueManager correctly serializes/deserializes models."""
    queue = db_memory.queue("tasks_model", model=Task)

    task1 = Task(action="compute", task_id=123)
    queue.put(task1, priority=1)

    item = queue.get(block=False)

    assert isinstance(item, QueueItem)
    assert isinstance(item.data, Task)
    assert item.data.action == "compute"
    assert item.data.task_id == 123
    assert item.priority == 1

def test_queue_dump(db_memory: BeaverDB):
    """Tests the .dump() method for a queue."""
    queue = db_memory.queue("test_dump")
    queue.put("task-b", priority=10)
    queue.put("task-a", priority=1)

    dump_data = queue.dump()

    assert dump_data["metadata"]["type"] == "Queue"
    assert dump_data["metadata"]["name"] == "test_dump"
    assert dump_data["metadata"]["count"] == 2

    items = dump_data["items"]
    assert len(items) == 2

    # Items should be in priority order
    assert items[0]["data"] == "task-a"
    assert items[0]["priority"] == 1

    assert items[1]["data"] == "task-b"
    assert items[1]["priority"] == 10

def test_queue_dump_with_model(db_memory: BeaverDB):
    """Tests that .dump() correctly serializes model instances."""
    queue = db_memory.queue("tasks_dump_model", model=Task)
    task1 = Task(action="compute", task_id=123)
    queue.put(task1, priority=1)

    dump_data = queue.dump()

    assert dump_data["metadata"]["count"] == 1
    # Ensure the item's data is a dict (JSON-serialized)
    assert dump_data["items"][0]["data"] == {"action": "compute", "task_id": 123}
    assert dump_data["items"][0]["priority"] == 1

def test_queue_iter(db_memory: BeaverDB):
    """Tests that __iter__ yields all items in order without removing them."""
    queue = db_memory.queue("test_iter")
    queue.put("task-b", priority=10)
    queue.put("task-a", priority=1)
    queue.put("task-c", priority=20)

    items = list(queue) # Calls __iter__

    assert len(items) == 3
    assert isinstance(items[0], QueueItem)
    assert items[0].data == "task-a"
    assert items[1].data == "task-b"
    assert items[2].data == "task-c"

    # Ensure items are still in the queue
    assert len(queue) == 3

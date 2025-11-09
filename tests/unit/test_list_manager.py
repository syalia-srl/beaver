from pydantic import BaseModel
import pytest
from beaver import BeaverDB

pytestmark = pytest.mark.unit

# --- Test Model for Serialization ---
class Person(BaseModel):
    name: str
    age: int

# --- Test Cases ---

# 1. Basic Stack/Queue Operations

def test_list_push_and_len(db_memory: BeaverDB):
    """Tests basic push and __len__."""
    my_list = db_memory.list("test_push_len")
    assert len(my_list) == 0
    my_list.push("a")
    my_list.push("b")
    my_list.push("c")
    assert len(my_list) == 3

def test_list_pop(db_memory: BeaverDB):
    """Tests that pop removes from the end (LIFO)."""
    my_list = db_memory.list("test_pop")
    my_list.push("a")
    my_list.push("b")
    assert my_list.pop() == "b"
    assert len(my_list) == 1
    assert my_list.pop() == "a"
    assert len(my_list) == 0

def test_list_pop_empty(db_memory: BeaverDB):
    """Tests that pop on an empty list returns None."""
    my_list = db_memory.list("test_pop_empty")
    assert len(my_list) == 0
    assert my_list.pop() is None
    assert len(my_list) == 0

def test_list_prepend(db_memory: BeaverDB):
    """Tests that prepend adds to the beginning."""
    my_list = db_memory.list("test_prepend")
    my_list.prepend("a")
    my_list.prepend("b") # Should be at the front
    assert len(my_list) == 2
    assert my_list[0] == "b"
    assert my_list[1] == "a"

def test_list_deque(db_memory: BeaverDB):
    """Tests that deque removes from the beginning (FIFO)."""
    my_list = db_memory.list("test_deque")
    my_list.push("a")
    my_list.push("b")
    assert my_list.deque() == "a"
    assert len(my_list) == 1
    assert my_list.deque() == "b"
    assert len(my_list) == 0

def test_list_deque_empty(db_memory: BeaverDB):
    """Tests that deque on an empty list returns None."""
    my_list = db_memory.list("test_deque_empty")
    assert len(my_list) == 0
    assert my_list.deque() is None
    assert len(my_list) == 0

# 2. Pythonic Indexing and Slicing

def test_list_get_item_positive_and_negative(db_memory: BeaverDB):
    """Tests __getitem__ with positive and negative indices."""
    my_list = db_memory.list("test_getitem")
    my_list.push("a")
    my_list.push("b")
    my_list.push("c")
    assert my_list[0] == "a"
    assert my_list[1] == "b"
    assert my_list[2] == "c"
    assert my_list[-1] == "c"
    assert my_list[-2] == "b"
    assert my_list[-3] == "a"

def test_list_get_item_out_of_bounds(db_memory: BeaverDB):
    """Tests that __getitem__ raises IndexError for invalid indices."""
    my_list = db_memory.list("test_getitem_bounds")
    my_list.push("a")
    with pytest.raises(IndexError):
        _ = my_list[1]
    with pytest.raises(IndexError):
        _ = my_list[-2]

def test_list_set_item(db_memory: BeaverDB):
    """Tests __setitem__ with positive and negative indices."""
    my_list = db_memory.list("test_setitem")
    my_list.push("a")
    my_list.push("b")
    my_list.push("c")
    my_list[1] = "new_b"
    assert my_list[1] == "new_b"
    my_list[-1] = "new_c"
    assert my_list[2] == "new_c"
    # Verify the entire list state
    assert my_list[:] == ["a", "new_b", "new_c"]

def test_list_set_item_out_of_bounds(db_memory: BeaverDB):
    """Tests that __setitem__ raises IndexError for invalid indices."""
    my_list = db_memory.list("test_setitem_bounds")
    my_list.push("a")
    with pytest.raises(IndexError):
        my_list[1] = "fail"
    with pytest.raises(IndexError):
        my_list[-2] = "fail"

def test_list_del_item(db_memory: BeaverDB):
    """Tests __delitem__ with positive and negative indices."""
    my_list = db_memory.list("test_delitem")
    my_list.push("a")
    my_list.push("b")
    my_list.push("c")
    del my_list[1] # Deletes "b"
    assert len(my_list) == 2
    assert my_list[0] == "a"
    assert my_list[1] == "c"
    del my_list[-1] # Deletes "c"
    assert len(my_list) == 1
    assert my_list[0] == "a"

def test_list_del_item_out_of_bounds(db_memory: BeaverDB):
    """Tests that __delitem__ raises IndexError for invalid indices."""
    my_list = db_memory.list("test_delitem_bounds")
    my_list.push("a")
    with pytest.raises(IndexError):
        del my_list[1]
    with pytest.raises(IndexError):
        del my_list[-2]

def test_list_slicing(db_memory: BeaverDB):
    """Tests __getitem__ with various slice operations."""
    my_list = db_memory.list("test_slicing")
    for i in range(5):
        my_list.push(i) # [0, 1, 2, 3, 4]

    assert my_list[:] == [0, 1, 2, 3, 4]
    assert my_list[1:3] == [1, 2]
    assert my_list[2:] == [2, 3, 4]
    assert my_list[:2] == [0, 1]
    assert my_list[-2:] == [3, 4]
    assert my_list[1:-1] == [1, 2, 3]
    assert my_list[-3:-1] == [2, 3]

def test_list_slicing_with_step_raises_error(db_memory: BeaverDB):
    """Tests that slicing with a step is not supported."""
    my_list = db_memory.list("test_slicing_step")
    my_list.push(0)
    my_list.push(1)
    with pytest.raises(ValueError):
        _ = my_list[::2]

# 3. Other Core Methods

def test_list_insert(db_memory: BeaverDB):
    """Tests insertion at various points in the list."""
    my_list = db_memory.list("test_insert")
    my_list.push("a")
    my_list.push("c")
    my_list.insert(1, "b") # Insert in middle
    assert my_list[:] == ["a", "b", "c"]
    my_list.insert(0, "start") # Insert at start (equiv to prepend)
    assert my_list[0] == "start"
    assert my_list[:] == ["start", "a", "b", "c"]
    my_list.insert(99, "end") # Insert at end (equiv to push)
    assert my_list[-1] == "end"
    assert len(my_list) == 5

def test_list_contains(db_memory: BeaverDB):
    """Tests the __contains__ (in) operator."""
    my_list = db_memory.list("test_contains")
    my_list.push("a")
    my_list.push({"id": 1})
    assert "a" in my_list
    assert {"id": 1} in my_list
    assert "b" not in my_list
    assert {"id": 2} not in my_list

def test_list_iter(db_memory: BeaverDB):
    """Tests the __iter__ method."""
    my_list = db_memory.list("test_iter")
    my_list.push("a")
    my_list.push("b")
    my_list.push("c")
    items = list(my_list)
    assert items == ["a", "b", "c"]

# 4. Advanced Features (Serialization & Dump)

def test_list_with_model_serialization(db_memory: BeaverDB):
    """Tests that the ListManager correctly serializes/deserializes models."""
    people = db_memory.list("people_model", model=Person)
    alice = Person(name="Alice", age=30)
    people.push(alice)

    retrieved = people[0]
    assert isinstance(retrieved, Person)
    assert retrieved.name == "Alice"
    assert retrieved.age == 30

    popped = people.pop()
    assert isinstance(popped, Person)
    assert popped.name == "Alice" # Check value from popped item
    assert popped.age == 30

def test_list_contains_with_model(db_memory: BeaverDB):
    """Tests the __contains__ operator with serialized models."""
    people = db_memory.list("people_contains", model=Person)
    alice = Person(name="Alice", age=30)
    bob = Person(name="Bob", age=40)
    people.push(alice)
    assert alice in people
    assert bob not in people

def test_list_dump(db_memory: BeaverDB):
    """Tests the .dump() method for a standard list."""
    my_list = db_memory.list("test_dump")
    my_list.push("a")
    my_list.push({"b": 1})

    dump_data = my_list.dump()

    assert dump_data["metadata"]["type"] == "List"
    assert dump_data["metadata"]["name"] == "test_dump"
    assert dump_data["metadata"]["count"] == 2
    assert dump_data["items"] == ["a", {"b": 1}]

def test_list_dump_with_model(db_memory: BeaverDB):
    """Tests that .dump() correctly serializes model instances."""
    people = db_memory.list("people_dump", model=Person)
    people.push(Person(name="Alice", age=30))

    dump_data = people.dump()

    assert dump_data["metadata"]["count"] == 1
    # Ensure the item is a dict (JSON-serialized), not a Person object
    assert dump_data["items"] == [{"name": "Alice", "age": 30}]

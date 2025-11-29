import pytest
import queue
import time
from beaver import BeaverDB, Document
from beaver.manager import EventHandle

# Mark all tests in this file as 'integration'
pytestmark = pytest.mark.integration
pytest.skip(allow_module_level=True)

# --- Test Helpers ---


def create_event_handler():
    """
    Creates a thread-safe queue and a handler function.
    The handler will put any payload it receives into the queue.
    """
    q = queue.Queue()

    def handler(payload):
        q.put(payload)

    return q, handler


def assert_event_received(q: queue.Queue, expected_payload: dict, timeout: float = 0.1):
    """
    Asserts that a specific payload is received in the queue within the timeout.
    """
    try:
        payload = q.get(timeout=timeout)
        assert payload == expected_payload
    except queue.Empty:
        pytest.fail(f"Did not receive event within {timeout}s")
    except AssertionError:
        pytest.fail(
            f"Received unexpected payload. Got: {payload}, Expected: {expected_payload}"
        )


def assert_no_event(q: queue.Queue, timeout: float = 0.1):
    """Asserts that no event is received."""
    with pytest.raises(queue.Empty):
        q.get(timeout=timeout)


# --- Test Cases ---


def test_manager_custom_event_emit(db: BeaverDB):
    """
    Tests the low-level event system using a manager's .on()
    and the db's .emit() to simulate a custom event.
    """
    q, handler = create_event_handler()

    # Use a real manager to get the .on() method and topic

    db.on("topic", "event", handler)

    # Give the listener thread time to register the subscription
    # The event registry needs to be updated and the pub/sub poller needs to see it
    time.sleep(0.1)

    # 1. Test Emit
    payload = {"data": "test_payload_123"}
    db.emit("topic", "event", payload)
    assert_event_received(q, payload)

    # 2. Test handle.off()
    db.off("topic", "event", handler)

    # Emit again, but this time it should not be received
    db.emit("topic", "event", {"data": "should_not_receive"})
    assert_no_event(q)


def test_dict_events(db: BeaverDB):
    """Tests the built-in events for DictManager."""
    q, handler = create_event_handler()
    d = db.dict("test_dict_events")
    d.clear()

    # Test set
    handle_set = d.on("set", handler)
    time.sleep(0.1)  # Allow subscription to register
    d["my_key"] = "my_value"
    assert_event_received(q, {"key": "my_key"})
    handle_set.off()

    # Test del
    handle_del = d.on("del", handler)
    time.sleep(0.1)
    del d["my_key"]
    assert_event_received(q, {"key": "my_key"})
    handle_del.off()

    # Test clear
    handle_clear = d.on("clear", handler)
    d["another_key"] = 1  # Add data to clear
    time.sleep(0.1)
    d.clear()
    assert_event_received(q, {})
    handle_clear.off()


def test_list_events(db: BeaverDB):
    """Tests the built-in events for ListManager."""
    q, handler = create_event_handler()
    l = db.list("test_list_events")
    l.clear()

    # Test push
    handle_push = l.on("push", handler)
    time.sleep(0.1)
    l.push("a")  # index 0
    assert_event_received(q, {})
    handle_push.off()

    # Test pop
    handle_pop = l.on("pop", handler)
    time.sleep(0.1)
    l.pop()
    assert_event_received(q, {})
    handle_pop.off()

    # Test setitem
    l.push("a")  # index 0
    handle_set = l.on("set", handler)
    time.sleep(0.1)
    l[0] = "b"
    assert_event_received(q, {"index": 0})
    handle_set.off()

    # Test delitem
    handle_del = l.on("del", handler)
    time.sleep(0.1)
    del l[0]
    assert_event_received(q, {"index": 0})
    handle_del.off()

    # Test insert
    handle_insert = l.on("insert", handler)
    time.sleep(0.1)
    l.insert(0, "new_front")
    assert_event_received(q, {"index": 0})
    handle_insert.off()


def test_queue_events(db: BeaverDB):
    """Tests the built-in events for QueueManager."""
    q, handler = create_event_handler()
    task_q = db.queue("test_queue_events")
    task_q.clear()

    # Test put
    handle_put = task_q.on("put", handler)
    time.sleep(0.1)
    task_q.put("task1", priority=1)
    assert_event_received(q, {})
    handle_put.off()

    # Test get
    handle_get = task_q.on("get", handler)
    time.sleep(0.1)
    item = task_q.get(block=False)
    assert item.data == "task1"
    assert_event_received(q, {})
    handle_get.off()


def test_collection_events(db: BeaverDB):
    """Tests the built-in events for CollectionManager."""
    q, handler = create_event_handler()
    c = db.collection("test_collection_events")
    c.clear()

    doc1 = Document(id="doc1", body={"content": "test"})
    doc2 = Document(id="doc2", body={"content": "test2"})

    # Test index
    handle_index = c.on("index", handler)
    time.sleep(0.1)
    c.index(doc1)
    assert_event_received(q, {"id": "doc1"})

    # Test upsert (also an 'index' event)
    doc1_updated = Document(id="doc1", body={"content": "updated"})
    c.index(doc1_updated)
    assert_event_received(q, {"id": "doc1"})
    handle_index.off()

    # Test drop
    handle_drop = c.on("drop", handler)
    time.sleep(0.1)
    c.drop(doc1)
    assert_event_received(q, {"id": "doc1"})
    handle_drop.off()

    # Test connect
    c.index(doc1)  # Re-index doc1
    c.index(doc2)
    handle_connect = c.on("connect", handler)
    time.sleep(0.1)
    c.connect(doc1, doc2, "LINKS_TO")
    assert_event_received(q, {"src_id": "doc1", "tgt_id": "doc2"})
    handle_connect.off()

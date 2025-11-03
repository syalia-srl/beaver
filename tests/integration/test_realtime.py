import pytest
import threading
import time
import statistics
from datetime import timedelta
from queue import Queue

from beaver import BeaverDB, Model
from beaver.channels import ChannelManager

# Mark all tests in this file as 'integration'
pytestmark = pytest.mark.integration

# --- Test Model for Serialization ---
class Event(Model):
    type: str
    value: int

# --- 1. QueueManager Tests ---

def test_queue_blocking_get(db: BeaverDB):
    """
    Tests that queue.get(block=True) blocks until an item is
    published from another thread.
    """
    queue = db.queue("test_blocking_get")
    result_queue = Queue() # Thread-safe queue to get results back

    def _worker():
        try:
            # This will block until an item is available or timeout
            item = queue.get(block=True, timeout=2.0)
            result_queue.put(item)
        except Exception as e:
            result_queue.put(e)

    # Start the worker thread, which will block
    t = threading.Thread(target=_worker)
    t.start()

    # Give the thread time to start and block
    time.sleep(0.1)

    # Now, publish the item
    queue.put("task-1", priority=1)

    # Wait for the thread to finish
    t.join(timeout=3.0)

    # Check that the thread finished (didn't time out)
    assert not t.is_alive()

    # Check that we got the item
    result = result_queue.get()
    assert not isinstance(result, Exception)
    assert result.data == "task-1"

# --- 2. ChannelManager (Pub/Sub) Tests ---

def _subscriber_worker(channel: ChannelManager, result_queue: Queue, ready_event: threading.Event):
    """A worker that subscribes and listens for one message."""
    try:
        with channel.subscribe() as listener:
            # Signal to the main thread that we are subscribed and listening
            ready_event.set()
            # Block and wait for a message
            for message in listener.listen(timeout=2.0):
                result_queue.put(message)
                break # Exit after one message
    except Exception as e:
        result_queue.put(e)

def test_channel_subscribe_receive(db: BeaverDB):
    """Tests that a subscriber in a thread receives a published message."""
    channel = db.channel("test_pubsub_1", model=Event)
    result_queue = Queue()
    ready_event = threading.Event()

    t = threading.Thread(
        target=_subscriber_worker,
        args=(channel, result_queue, ready_event)
    )
    t.start()

    # Wait for the subscriber thread to be ready
    assert ready_event.wait(timeout=2.0), "Subscriber thread failed to start"

    # Publish the event
    event = Event(type="click", value=123)
    channel.publish(event)

    t.join(timeout=3.0)
    assert not t.is_alive()

    # Check that the subscriber received the correct message
    result = result_queue.get()
    assert not isinstance(result, Exception)
    assert isinstance(result, Event)
    assert result.type == "click"
    assert result.value == 123

def test_channel_multi_subscribe_fanout(db: BeaverDB):
    """Tests that multiple subscribers (fan-out) all receive the same message."""
    channel = db.channel("test_pubsub_fanout")

    # Create two subscribers
    q1, q2 = Queue(), Queue()
    e1, e2 = threading.Event(), threading.Event()

    t1 = threading.Thread(target=_subscriber_worker, args=(channel, q1, e1))
    t2 = threading.Thread(target=_subscriber_worker, args=(channel, q2, e2))

    t1.start()
    t2.start()

    # Wait for both to be ready
    assert e1.wait(timeout=2.0), "Subscriber 1 failed to start"
    assert e2.wait(timeout=2.0), "Subscriber 2 failed to start"

    # Publish one message
    channel.publish("fanout_test")

    t1.join(timeout=3.0)
    t2.join(timeout=3.0)

    # Check that both threads finished and received the message
    assert not t1.is_alive()
    assert not t2.is_alive()

    result1 = q1.get()
    result2 = q2.get()

    assert not isinstance(result1, Exception)
    assert not isinstance(result2, Exception)
    assert result1 == "fanout_test"
    assert result2 == "fanout_test"

# --- 3. LogManager (Live) Tests ---

def _aggregator(window: list) -> dict:
    """A test aggregator for the log.live() method."""
    if not window:
        return {"count": 0, "sum": 0}
    values = [item.get("value", 0) for item in window]
    return {"count": len(values), "sum": sum(values)}

def test_log_live_receive(db: BeaverDB):
    """Tests that the log.live() iterator yields new aggregations."""
    logs = db.log("test_live_log")
    result_queue = Queue()
    ready_event = threading.Event()

    def _log_watcher():
        try:
            # Use a short window and period for fast testing
            live_stream = logs.live(
                window=timedelta(seconds=1),
                period=timedelta(seconds=0.1),
                aggregator=_aggregator
            )

            iterator = iter(live_stream)

            # Get the initial result (likely empty)
            initial_result = next(iterator)
            result_queue.put(initial_result)

            # Signal that we are ready
            ready_event.set()

            # Block and wait for the *next* aggregated result
            # This will only happen after a log is added
            next_result = next(iterator)
            result_queue.put(next_result)
        except Exception as e:
            result_queue.put(e)

    t = threading.Thread(target=_log_watcher)
    t.start()

    assert ready_event.wait(timeout=2.0), "Log watcher thread failed to start"

    # Log a new entry
    logs.log({"value": 10})

    t.join(timeout=3.0)
    assert not t.is_alive()

    # We expect two results: initial and updated
    initial = result_queue.get()
    updated = result_queue.get()

    assert not isinstance(initial, Exception)
    assert not isinstance(updated, Exception)

    # Initial result should be empty or contain the new item (timing-dependent)
    assert initial["count"] in [0, 1]

    # Updated result must contain the new item
    assert updated["count"] >= 1
    assert updated["sum"] >= 10

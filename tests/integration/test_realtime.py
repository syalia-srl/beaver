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
    result_queue = Queue()  # Thread-safe queue to get results back

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


def _subscriber_worker(channel: ChannelManager, result_queue: Queue):
    """A worker that subscribes and listens for one message."""
    try:
        with channel.subscribe() as listener:
            # Block and wait for a message
            for message in listener.listen(timeout=2.0):
                result_queue.put(message)
                break  # Exit after one message
    except Exception as e:
        result_queue.put(e)


def test_channel_subscribe_receive(db: BeaverDB):
    """Tests that a subscriber in a thread receives a published message."""
    channel = db.channel("test_pubsub_1", model=Event)
    result_queue = Queue()

    t = threading.Thread(target=_subscriber_worker, args=(channel, result_queue))
    t.start()

    # Give the worker time to susbcribe
    time.sleep(0.1)

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
    qs = [Queue() for _ in range(10)]
    ts = [threading.Thread(target=_subscriber_worker, args=(channel, q)) for q in qs]

    for t in ts:
        t.start()

    # Give the subscribers time to start
    time.sleep(0.1)

    # Publish one message
    channel.publish("fanout_test")

    for t, q in zip(ts, qs):
        t.join(1)
        assert not t.is_alive()
        r = q.get()
        assert not isinstance(r, Exception)
        assert r == "fanout_test"


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

    def _log_watcher():
        try:
            # Use a short window and period for fast testing
            live_stream = logs.live(
                window=timedelta(seconds=10),
                period=timedelta(seconds=0.1),
                aggregator=_aggregator,
            )

            iterator = iter(live_stream)

            result = next(iterator)
            result_queue.put(result)

        except Exception as e:
            result_queue.put(e)

    # Log a new entry
    logs.log({"value": 1})
    logs.log({"value": 2})
    logs.log({"value": 3})
    logs.log({"value": 4})
    logs.log({"value": 5})

    t = threading.Thread(target=_log_watcher)
    t.start()

    t.join(timeout=3.0)
    assert not t.is_alive()

    # We expect two results: initial and updated
    results = result_queue.get()
    assert not isinstance(results, Exception)

    assert results["count"] == 5
    assert results["sum"] == sum([1, 2, 3, 4, 5])

import asyncio
import threading
import pytest
from beaver.bridge import BeaverBridge

# --- Mocks ---


class MockAsyncBatch:
    """
    Represents the object yielded by the context manager (e.g. DictBatch).
    This is what we want the Bridge to wrap automatically.
    """

    def __init__(self):
        self.operations = []

    async def put(self, key, value):
        self.operations.append((key, value))


class MockBatchContext:
    """
    Represents the Async Context Manager returned by .batched().
    """

    def __init__(self):
        self.batch = MockAsyncBatch()
        self.entered = False
        self.exited = False

    async def __aenter__(self):
        self.entered = True
        # Return a DIFFERENT object (the batch) to verify recursive bridging
        return self.batch

    async def __aexit__(self, exc_type, exc, tb):
        self.exited = True


class MockAsyncObject:
    """
    A mock object mimicking an AsyncBeaver* manager.
    """

    def __init__(self):
        self.data = {}
        self.simple_property = "I am sync"

    async def echo(self, value, delay=0.0):
        if delay:
            await asyncio.sleep(delay)
        return value

    async def fail(self):
        raise ValueError("Async failure!")

    def batched(self):
        """Returns the async context manager."""
        return MockBatchContext()

    # --- Magic Method Mappings ---

    async def count(self):
        return len(self.data)

    async def get(self, key):
        return self.data[key]

    async def set(self, key, value):
        self.data[key] = value

    async def delete(self, key):
        del self.data[key]

    async def contains(self, key):
        return key in self.data

    async def __aiter__(self):
        for key in self.data:
            yield key

    # --- Context Manager (Self) ---
    # Simulates objects like LockManager that return 'self' on enter

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        pass


# --- Fixtures ---


@pytest.fixture
def event_loop_thread():
    """
    Starts a real asyncio loop in a background thread,
    mimicking the behavior of BeaverDB.
    """
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()

    yield loop

    # Teardown
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=1.0)


@pytest.fixture
def bridge_and_mock(event_loop_thread):
    mock = MockAsyncObject()
    bridge = BeaverBridge(mock, event_loop_thread)
    return bridge, mock


# --- Tests ---


def test_property_access(bridge_and_mock):
    """Test accessing standard synchronous properties."""
    bridge, mock = bridge_and_mock
    assert bridge.simple_property == "I am sync"


def test_dynamic_method_proxy(bridge_and_mock):
    """Test calling an async method synchronously via the bridge."""
    bridge, mock = bridge_and_mock
    # .echo() is async on the mock, but sync on the bridge
    result = bridge.echo("hello world")
    assert result == "hello world"


def test_exception_propagation(bridge_and_mock):
    """Test that exceptions from the async thread bubble up correctly."""
    bridge, mock = bridge_and_mock
    with pytest.raises(ValueError, match="Async failure!"):
        bridge.fail()


def test_magic_len(bridge_and_mock):
    """Test __len__ mapping to await .count()."""
    bridge, mock = bridge_and_mock
    mock.data = {"a": 1, "b": 2}
    assert len(bridge) == 2


def test_magic_getitem_setitem(bridge_and_mock):
    """Test dictionary-style access mapping."""
    bridge, mock = bridge_and_mock

    bridge["key"] = "value"
    assert mock.data["key"] == "value"

    assert bridge["key"] == "value"

    with pytest.raises(KeyError):
        _ = bridge["missing"]


def test_magic_delitem(bridge_and_mock):
    """Test __delitem__ mapping."""
    bridge, mock = bridge_and_mock
    mock.data = {"target": 1}

    del bridge["target"]
    assert "target" not in mock.data


def test_magic_contains(bridge_and_mock):
    """Test 'in' operator mapping."""
    bridge, mock = bridge_and_mock
    mock.data = {"exists": 1}

    assert "exists" in bridge
    assert "missing" not in bridge


def test_magic_iter(bridge_and_mock):
    """Test iterating over the bridge consumes the async iterator."""
    bridge, mock = bridge_and_mock
    mock.data = {"a": 1, "b": 2, "c": 3}

    # This runs the async generator on the background thread
    keys = list(bridge)
    assert sorted(keys) == ["a", "b", "c"]


def test_context_manager_reentrant(bridge_and_mock):
    """
    Test a context manager that returns itself (e.g. LockManager).
    The bridge should recognize `result is self` and NOT re-wrap it.
    """
    bridge, mock = bridge_and_mock

    with bridge as b:
        # Must return the EXACT SAME bridge instance
        assert b is bridge
        assert b.echo("inside") == "inside"


def test_context_manager_recursive_wrap(bridge_and_mock, event_loop_thread):
    """
    Test a context manager that returns a DIFFERENT object (e.g. .batched()).
    The bridge must detect this and wrap the result in a NEW BeaverBridge automatically.
    """
    bridge, mock = bridge_and_mock

    # 1. Get the async context manager from the bridge
    # Note: BeaverBridge proxies the call, so 'ctx_raw' is the raw MockBatchContext
    # sitting in the main thread.
    ctx_raw = bridge.batched()

    # 2. Wrap it in a bridge manually (This simulates what the Sync Factory
    # would do: return BeaverBridge(async_manager.batched(), loop))
    ctx_bridge = BeaverBridge(ctx_raw, event_loop_thread)

    # 3. Enter the context
    with ctx_bridge as batch_bridge:
        # --- VERIFICATION ---

        # A. Verify we are inside the context
        assert ctx_raw.entered is True

        # B. Verify the object yielded is a Bridge, not the raw Batch
        assert isinstance(batch_bridge, BeaverBridge)
        assert not isinstance(batch_bridge, MockAsyncBatch)
        assert isinstance(batch_bridge._async_obj, MockAsyncBatch)

        # C. Verify we can call async methods on the batch synchronously
        batch_bridge.put("item1", "value1")

        # Check side effects on the raw mock
        assert ctx_raw.batch.operations == [("item1", "value1")]

    # 4. Verify exit
    assert ctx_raw.exited is True


# --- Mocks ---


class MockAsyncIterObject:
    """
    Mock mimicking an AsyncBeaver* manager with generator methods.
    """

    def __init__(self):
        self.data = ["a", "b", "c"]

    async def __aiter__(self):
        """Standard iteration (handled by __iter__)."""
        for item in self.data:
            yield item

    async def keys(self):
        """
        Method returning an async generator.
        WITHOUT _SyncIteratorBridge, this returns a raw async_generator object
        to the sync world, which crashes when you try to loop over it.
        """
        for item in self.data:
            yield f"key:{item}"

    async def live(self):
        """
        Infinite stream simulation (like LogManager.live()).
        """
        yield "event1"
        yield "event2"
        # In real life this might run forever, here we stop for testing


# --- Tests ---


def test_method_returning_async_generator(event_loop_thread):
    """
    This test verifies that calling a method like .keys() or .live()
    returns a SYNCHRONOUS iterator that works in a standard for-loop.
    """
    mock = MockAsyncIterObject()
    bridge = BeaverBridge(mock, event_loop_thread)

    # 1. Test standard iteration (This worked with the previous fix)
    assert list(bridge) == ["a", "b", "c"]

    # 2. Test method returning generator (THIS SHOULD FAIL without _SyncIteratorBridge)
    # The bridge must detect the async generator result and wrap it.
    gen = bridge.keys()

    # If the bridge fails, 'gen' is an <async_generator object ...>
    # and list(gen) raises TypeError.
    results = list(gen)

    assert results == ["key:a", "key:b", "key:c"]


def test_manual_next_advancement(event_loop_thread):
    """
    Verify we can manually drive the iterator with next().
    """
    mock = MockAsyncIterObject()
    bridge = BeaverBridge(mock, event_loop_thread)

    live_iter = bridge.live()

    assert next(live_iter) == "event1"
    assert next(live_iter) == "event2"

    with pytest.raises(StopIteration):
        next(live_iter)

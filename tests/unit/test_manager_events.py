import asyncio
import pytest
from beaver import AsyncBeaverDB, Event

pytestmark = pytest.mark.asyncio


async def test_manager_emits_decorator(async_db_mem: AsyncBeaverDB):
    """Test that @emits decorator correctly triggers the event manager."""
    d = async_db_mem.dict("notified_dict")

    received = []

    async def on_set(event: Event):
        received.append(event.payload)

    # Attach via the portal method .on()
    await d.on("set", on_set)
    await asyncio.sleep(0.1)

    # Trigger operation decorated with @emits("set")
    await d.set("key", "value")

    # Wait for dispatch
    await asyncio.sleep(0.2)

    assert len(received) == 1
    # The payload lambda for set is: lambda key, ...: dict(key=key)
    assert received[0] == {"key": "key"}


async def test_manager_events_property(async_db_mem: AsyncBeaverDB):
    """Test accessing the .events manager directly."""
    l = async_db_mem.list("event_list")

    # Check property exists and is typed
    assert l.events is not None

    # Use .events.emit() manually
    await l.events.emit("custom_event", {"msg": "hello"})

    # We need a listener to verify it worked
    msgs = []
    await l.events.attach("custom_event", lambda e: msgs.append(e.payload))

    # Re-emit
    await l.events.emit("custom_event", {"msg": "world"})
    await asyncio.sleep(0.2)

    assert msgs == [{"msg": "world"}]

import asyncio
import pytest
from pydantic import BaseModel
from beaver import AsyncBeaverDB, Event

pytestmark = pytest.mark.asyncio


class User(BaseModel):
    name: str
    role: str = "user"


async def test_events_attach_emit(async_db_mem: AsyncBeaverDB):
    """Test basic attach and emit flow with both sync and async callbacks."""
    events = async_db_mem.events("auth", model=User)

    received = []

    # 1. Async Callback
    async def on_login_async(event: Event[User]):
        received.append(f"async:{event.payload.name}")

    # 2. Sync Callback
    def on_login_sync(event: Event[User]):
        received.append(f"sync:{event.payload.name}")

    # Attach
    await events.attach("login", on_login_async)
    await events.attach("login", on_login_sync)

    # Wait for listener to start
    await asyncio.sleep(0.1)

    # Emit
    await events.emit("login", User(name="Alice"))

    # Wait for dispatch
    await asyncio.sleep(0.2)

    # Check results (order not guaranteed, but usually predictable here)
    assert len(received) == 2
    assert "async:Alice" in received
    assert "sync:Alice" in received


async def test_events_detach(async_db_mem: AsyncBeaverDB):
    """Test detaching callbacks."""
    events = async_db_mem.events("notifications")

    msgs = []

    async def handler(event: Event):
        msgs.append(event.payload)

    handle = await events.attach("ping", handler)
    await asyncio.sleep(0.1)

    # First emit
    await events.emit("ping", "one")
    await asyncio.sleep(0.1)
    assert msgs == ["one"]

    # Detach
    await handle.off()

    # Second emit
    await events.emit("ping", "two")
    await asyncio.sleep(0.1)

    # Should not receive "two"
    assert msgs == ["one"]


async def test_events_payload_validation(async_db_mem: AsyncBeaverDB):
    """Test that payloads are correctly validated into the Pydantic model."""
    events = async_db_mem.events("validated", model=User)

    validated_users: list[User] = []

    async def user_handler(event: Event[User]):
        validated_users.append(event.payload)

    await events.attach("signup", user_handler)
    await asyncio.sleep(0.1)

    # Emit with correct model
    await events.emit("signup", User(name="Bob"))
    await events.emit("signup", User(name="Charlie"))

    await asyncio.sleep(0.2)

    assert len(validated_users) == 2

    assert validated_users[0].name == "Bob"
    assert validated_users[1].name == "Charlie"


async def test_events_event_metadata(async_db_mem: AsyncBeaverDB):
    """Test that the Event envelope contains correct metadata."""
    events = async_db_mem.events("meta")

    async def handler(event: Event):
        assert event is not None
        assert event.event == "click"
        assert event.payload == "button1"
        assert event.id is not None
        assert event.timestamp > 0

    await events.attach("click", handler)
    await asyncio.sleep(0.1)

    await events.emit("click", "button1")
    await asyncio.sleep(0.1)

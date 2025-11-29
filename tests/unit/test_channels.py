import asyncio
from pydantic import BaseModel
import pytest
from beaver import AsyncBeaverDB

pytestmark = pytest.mark.asyncio


async def test_pubsub_basic(async_db_mem: AsyncBeaverDB):
    """Test publish and history retrieval."""
    ch = async_db_mem.channel("news")

    await ch.publish("hello")
    await ch.publish("world")

    # Check history
    msgs = await ch.history()
    assert len(msgs) == 2
    assert msgs[0].payload == "hello"
    assert msgs[1].payload == "world"


async def test_pubsub_subscribe(async_db_mem: AsyncBeaverDB):
    """Test live subscription receiving messages."""
    ch = async_db_mem.channel("chat")

    # 1. Start a consumer task
    received = []

    async def consumer():
        async for msg in ch.subscribe():
            received.append(msg.payload)
            if len(received) >= 2:
                break

    task = asyncio.create_task(consumer())

    # 2. Wait a bit for subscription to register
    await asyncio.sleep(0)

    # 3. Publish messages
    await ch.publish("msg1")
    await asyncio.sleep(0)  # Allow poll loop to cycle
    await ch.publish("msg2")

    # 4. Wait for consumer to finish
    await asyncio.wait_for(task, timeout=2.0)

    assert received == ["msg1", "msg2"]


async def test_pubsub_multi_subscriber(async_db_mem: AsyncBeaverDB):
    """Test fan-out to multiple subscribers."""
    ch = async_db_mem.channel("broadcast")

    async def sub():
        msgs = []
        async for msg in ch.subscribe():
            msgs.append(msg.payload)
            if len(msgs) == 1:
                break
        return msgs[0]

    t1 = asyncio.create_task(sub())
    t2 = asyncio.create_task(sub())

    await asyncio.sleep(0)
    await ch.publish("ping")

    results = await asyncio.gather(t1, t2)
    assert results == ["ping", "ping"]


async def test_pubsub_isolation(async_db_mem: AsyncBeaverDB):
    """Test that subscribers only receive messages for their channel."""
    ch1 = async_db_mem.channel("A")
    ch2 = async_db_mem.channel("B")

    received_a = []

    async def sub_a():
        async for msg in ch1.subscribe():
            received_a.append(msg.payload)
            if len(received_a) == 1:
                break

    t = asyncio.create_task(sub_a())
    await asyncio.sleep(0)

    await ch2.publish("noise")  # Should be ignored
    await ch1.publish("signal")  # Should be received

    await asyncio.wait_for(t, timeout=1.0)
    assert received_a == ["signal"]


async def test_channel_typed_model(async_db_mem: AsyncBeaverDB):
    """Test channels with a typed model."""

    class Message(BaseModel):
        text: str
        count: int

    ch = async_db_mem.channel("typed_ch", model=Message)

    await ch.publish(Message(text="hello", count=1))
    await asyncio.sleep(0.1)

    msgs = await ch.history(limit=1)
    assert len(msgs) == 1
    assert isinstance(msgs[0].payload, Message)
    assert msgs[0].payload.text == "hello"
    assert msgs[0].payload.count == 1

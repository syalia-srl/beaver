import pytest
from pydantic import BaseModel
from beaver import BeaverDB

# This is a synchronous test file
pytestmark = pytest.mark.integration


class User(BaseModel):
    name: str
    age: int


def test_sync_smoke_all_managers(db_mem: BeaverDB):
    """
    Smoke test to verify that the Synchronous Facade (BeaverDB) correctly
    wires up all managers via the Bridge and that basic operations work.
    """
    # 1. Dictionary
    d = db_mem.dict("smoke_dict", model=User)
    d["u1"] = User(name="Alice", age=30)
    assert d["u1"].name == "Alice"
    assert len(d) == 1

    # 2. List
    l = db_mem.list("smoke_list")
    l.push("item1")
    l.push("item2")
    assert l[0] == "item1"
    assert len(l) == 2

    # 3. Queue
    q = db_mem.queue("smoke_queue")
    q.put("high", priority=1)
    q.put("low", priority=10)
    item = q.get()
    assert item.data == "high"

    # 4. Blob
    b = db_mem.blob("smoke_blob")
    b.put("key", b"binary_data")
    assert b.get("key") == b"binary_data"

    # 5. Log
    log = db_mem.log("smoke_log")
    log.log("entry1")
    log.log("entry2")
    entries = log.range()
    assert len(entries) == 2
    assert entries[0].data == "entry1"

    # 6. Sketch
    s = db_mem.sketch("smoke_sketch")
    s.add("element")
    assert "element" in s
    # Cardinality is approx, but for 1 item it should be close
    assert s.count() >= 1

    # 7. Documents (New v2.0)
    docs = db_mem.docs("smoke_docs", model=User)
    doc = docs.index(body=User(name="Bob", age=25))
    assert doc.id is not None
    # FTS Search
    results = docs.search("Bob")
    assert len(results) == 1
    assert results[0].body.name == "Bob"

    # 8. Vectors (New v2.0)
    vecs = db_mem.vectors("smoke_vecs")
    vecs.set("v1", [1.0, 0.0])
    vecs.set("v2", [0.0, 1.0])
    # Search
    hits = vecs.search([0.9, 0.1], k=1)
    assert hits[0].id == "v1"

    # 9. Graph (New v2.0)
    g = db_mem.graph("smoke_graph")
    g.link("a", "b", "knows")
    assert g.linked("a", "b", "knows") is True
    # Traversal (Bridge handles Iterator mapping)
    neighbors = list(g.children("a"))
    assert neighbors == ["b"]

    # 10. Lock
    # Using context manager via Bridge
    with db_mem.lock("smoke_lock"):
        pass  # Just verify acquisition/release works

    # 11. Events (New v2.0)
    events = db_mem.events("smoke_events")

    received = []
    def on_msg(event):
        received.append(event.payload)

    events.attach("ping", on_msg)

    # Emit (async logic wrapped by bridge)
    events.emit("ping", "pong")

    # We might need to wait a bit for async propagation?
    # The bridge.run() awaits the emit coroutine, which awaits the DB insert.
    # But the LISTENER runs in the background task.
    # In a sync test, we might need a small sleep to allow the background task to cycle.
    import time
    time.sleep(0.5)

    assert "pong" in received

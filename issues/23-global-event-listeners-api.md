---
number: 23
title: "Global Event Listeners API"
state: open
labels:
---

## 1. Concept

This feature introduces an event-driven architecture to BeaverDB, allowing users to subscribe to changes happening within specific data structures.

We will leverage the existing ChannelManager (Pub/Sub) to broadcast these events. Crucially, to maintain BeaverDB's "lean by default" philosophy, events will only be published if there is at least one active listener for that specific topic.

## 2. Use Cases

- **Reactive UI Updates**: A desktop app re-renders when db.dict("settings") is updated by another process.

- **Triggered Workflows**: A background worker listens to db.collection("docs").on("index", ...) to trigger processing.

- **Audit Logging**: Logging all "delete" events across critical structures.

## 3. Proposed API

```python
db = BeaverDB("my_app.db")
config = db.dict("app_config")

def on_change(event):
    # event is {"event": "set", "name": "app_config", "id": "theme"}
    print(f"Key changed: {event['id']}")

# Subscribe to 'set' events on this specific dict
listener = config.on("set", on_change)

# ... later ...
config["theme"] = "dark" # Triggers callback anywhere

listener.close() # Clean up
```

## 4. Implementation Design

### A. The Registry (__beaver_events__ Dict)

We will use a standard internal DictManager named __beaver_events__ to track active listeners across all processes.

- Key: The standardized topic string (e.g., dict:app_config:set).
- Value: An integer count of active listeners across all processes.

### B. The BeaverDB.emit Gatekeeper (in beaver/core.py)

The emit method uses a two-tiered check to minimize overhead:

- **Tier 1 (Local Fast-Path)**: Check `self._local_event_topics` (in-memory dict). If present, publish immediately.
- **Tier 2 (IPC Check)**: If not local, check the shared registry: `self.dict("__beaver_events__").get(topic, 0) > 0`.
- **Publish**: If either tier is true, self.channel(topic).publish(payload).

### C. Standardized Topics & MVP Payloads

- Topics: `{manager_type}:{manager_name}:{event_type}` (e.g., `collection:articles:index`)

Payloads must be strictly minimal notifications (Identifiers only):

- `Dict` (set, del): `{"e": "set", "n": "name", "id": "key"}`
- `List` (push, pop, ...): `{"e": "push", "n": "name", "id": index_int}`
- `Collection` (index, drop): `{"e": "index", "n": "name", "id": "doc_uuid"}`
- `Queue` (put, get): `{"e": "put", "n": "name", "id": priority_float}`

### D. Manager Integration (`ManagerBase.on`)

#### Registration (`on(event_type, callback)`):

- Add topic to local `_local_event_topics`.
- Atomic Increment: Use the public lock to safely increment the shared registry count:

    ```python
    with self.db.dict("__beaver_events__") as registry:
        registry[topic] = registry.get(topic, 0) + 1
    ```

- Start local subscriber thread.

#### Deregistration (`close()`):

- Remove from local `_local_event_topics`.
- Atomic Decrement:

    ```python
    with self.db.dict("__beaver_events__") as registry:
        current = registry.get(topic, 1)
        if current <= 1: del registry[topic]
        else: registry[topic] = current - 1
    ```

- Stop local thread.

#### Cleanup on db.close():

The `BeaverDB.close()` method already iterates over all cached managers and calls their `.close()` method.

We must ensure `ManagerBase.close()` calls `stop()` on all active listeners for that manager to cleanly decrement the global registry.

## 5. High-Level Roadmap

Phase 1: Core Infrastructure

- Implement BeaverDB.emit() with the two-tiered check.
- Implement ManagerBase.on() with atomic registry updates.
- Ensure ManagerBase.close() cleans up listeners.

Phase 2: Instrument Managers

- Add emit() calls to all mutating methods in all managers using MVP payloads.

Phase 3: Testing

- Verify local callbacks work.
- Verify IPC: Process A listens, Process B modifies -> Process A gets callback.
- Verify zero overhead when no one is listening.
- Verify clean shutdown on db.close().
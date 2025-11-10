---
number: 22
title: "Add Context Manager support and robust process-wide cleanup to BeaverDB"
state: open
labels:
---

## 1. Concept

Currently, BeaverDB.close() only closes the SQLite connection for the current thread due to the use of threading.local. This means that in a multi-threaded application, calling db.close() on the main thread might leave connections open in other threads, potentially leading to file locks or resource leaks until the process terminates.

Furthermore, while ChannelManager has cleanup logic, LogManager does not currently track active .live() iterators, meaning their background threads might keep running after db.close().

This feature addresses this by:

Implementing a Connection Registry: Using a weakref.WeakSet to track every active SQLite connection created by a BeaverDB instance across all threads.

Improving .close(): Updating db.close() to iterate through this registry and forcibly close all tracked connections, AND ensure all background threads (Channels, Logs, future Event Listeners) are stopped.

Adding Context Manager Support: Implementing __enter__ and __exit__ on BeaverDB so users can easily leverage this robust cleanup via the with statement.

## 2. Justification

Robust Resource Management: Ensures that db.close() truly means "close this database instance entirely for this process," adhering to the principle of least surprise.

Prevents Resource Leaks: Critical for long-running applications (like web servers) where threads might come and go; we don't want zombie connections or orphaned polling threads hanging around.

Pythonic API: The with BeaverDB(...) as db: syntax is the standard, expected way to handle resources that require cleanup.

## 3. Proposed API

```python
from beaver import BeaverDB

# Standard usage:
with BeaverDB("my_app.db") as db:
    # .. threads can be spawned here, using 'db' ...
    # .. background tasks like db.log().live() can be started ...
    db.dict("settings")["theme"] = "dark"

# When this block exits, db.close() is called automatically.
# ALL connections are closed, and ALL background polling threads are stopped.
```

## 4. Implementation Plan

A. Modify BeaverDB.__init__ (beaver/core.py):
Initialize the registries.

```python
import weakref
# ...
self._connections = weakref.WeakSet()
self._connections_lock = threading.Lock()
# Existing _manager_cache will be used to find managers to close
```

B. Modify BeaverDB.connection property:
Register new connections when they are created.

```python
# ... inside if conn is None: ...
conn = sqlite3.connect(...)
# ... apply pragmas ...

with self._connections_lock:
    self._connections.add(conn)

self._thread_local.conn = conn
```

C. Update LogManager & LiveIterator (beaver/logs.py):
Implement close() and Context Manager on LiveIterator, and track them in LogManager.

```python
class LiveIterator:
    # ... existing methods ...
    def close(self):
        """Stops the background polling thread."""
        self._stop_event.set()
        # ... (wait for thread to join if needed) ...

    def __enter__(self):
        return self.__iter__()

    def __exit__(self, *args):
        self.close()

class LogManager(ManagerBase):
    def __init__(self, ...):
        super().__init__(...)
        # Use WeakSet so we don't keep iterators alive if the user drops them
        self._active_iterators = weakref.WeakSet()

    def live(self, ...):
        iterator = LiveIterator(...)
        self._active_iterators.add(iterator)
        return iterator

    def close(self):
        """Stops all active background polling threads for this log."""
        for iterator in self._active_iterators:
            iterator.close()
```

D. Update BeaverDB.close() (beaver/core.py):
Iterate and close all registered connections and managers.

```python
def close(self):
    if self._closed.is_set(): return
    self._closed.set()

    # 1. Shut down all managers (stops Channels, Logs, Event Listeners)
    with self._manager_cache_lock:
        for manager in self._manager_cache.values():
            if hasattr(manager, "close"):
                try:
                    manager.close()
                except Exception:
                    pass # Suppress errors during shutdown

    # 2. Force-close ALL tracked connections for this instance
    with self._connections_lock:
        for conn in self._connections:
            try:
                conn.close()
            except Exception:
                pass
        self._connections.clear()

    # ... (optional: clear current thread's local storage) ...
```

E. Implement Context Manager methods on BeaverDB:

```python
def __enter__(self) -> "BeaverDB":
    return self

def __exit__(self, exc_type, exc_val, exc_tb):
    self.close()
```

5. Documentation & Warnings

The documentation for `BeaverDB.close()` and the with statement must include a clear warning about this new behavior.

> Warning: Calling db.close() (or exiting a with block) will forcibly close database connections for all threads using that BeaverDB instance and immediately stop all background listeners (Pub/Sub, Live Logs, Event Callbacks). If other threads are in the middle of a database operation, they will immediately fail with a sqlite3.ProgrammingError.
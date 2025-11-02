---
number: 9
title: "Type-safe wrappers based on Pydantic-compatible models"
state: closed
labels:
---

### 1. Concept

This feature will introduce optional, type-safe wrappers for `beaver-db`'s data structures, powered by Pydantic. By allowing developers to associate a Pydantic model with a dictionary, list, or queue, the library will provide automatic data validation, serialization, and deserialization. This enhances the developer experience by enabling static analysis and autocompletion in modern editors.

### 2. Use Cases

* **Data Integrity**: Enforce a schema on your data at runtime, preventing corrupted or malformed data from being saved.
* **Improved Developer Experience**: Get full autocompletion and type-checking in your IDE, reducing bugs and improving productivity.
* **Automatic Serialization/Deserialization**: Seamlessly convert between Pydantic objects and JSON without boilerplate code.

### 3. Proposed API

The API is designed to be intuitive and "Pythonic", aligning with the existing design principles of the library.

```python
from pydantic import BaseModel
from beaver import BeaverDB

class Person(BaseModel):
    name: str
    age: int

db = BeaverDB("data.db")

# Dictionaries
users = db.dict("users", model=Person)
users["alice"] = Person(name="Alice", age=30)
alice = users["alice"] # Returns a Person object

# Lists
people = db.list("people", model=Person)
people.push(Person(name="Bob", age=40))
bob = people[0] # Returns a Person object

# Queues
tasks = db.queue("tasks", model=Person)
tasks.put(Person(name="Charlie", age=50), priority=1)
charlie_item = tasks.get()
charlie = charlie_item.data # Returns a Person object
```

### 4. Implementation Design: Generic Wrappers with Pydantic

The implementation will use Python's `typing.Generic` to create type-aware wrappers for the data structures.

* **Generic Managers**: `DictManager`, `ListManager`, and `QueueManager` will be converted to generic classes (e.g., `ListManager(Generic[T])`).
* **Serialization/Deserialization**: Internal `_serialize` and `_deserialize` methods will handle the conversion between Pydantic models and JSON strings.
* **Optional Dependency**: `pydantic` will be an optional dependency, installable via `pip install "beaver-db[pydantic]"`, to keep the core library lightweight.

### 5. Alignment with Philosophy

This feature aligns with `beaver-db`'s guiding principles:

* **Simplicity and Pythonic API**: The `model` parameter is a simple and intuitive way to enable type safety.
* **Developer Experience**: This feature directly addresses the developer experience by providing type safety and editor support.
* **Minimal & Cross-Platform Dependencies**: By making `pydantic` an optional dependency, the core library remains minimalistic.
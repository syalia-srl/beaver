---
number: 13
title: "Refactor - Adopt Pydantic, Deprecate `beaver.Model`, and Refactor `Document` to be Generic"
state: open
labels:
---

### 1. Concept

This feature plan outlines a foundational refactor to our type-safety model, resolving the core problems in Issue #9.

Our current custom `beaver.Model` is a "leaky abstraction." It provides serialization but fails to recursively deserialize nested objects, creating a confusing and buggy developer experience. To fix this properly would mean reimplementing Pydantic, which is complex and violates our "Simplicity" principle.

This refactor proposes a new hybrid approach:
1.  **Adopt Pydantic as a Core Dependency:** We will add `pydantic` to the main project dependencies. This is a trade-off, prioritizing "Developer Experience" and "Simplicity" over a strict "Minimal Dependency" rule. This is justified as Pydantic is the *de facto* standard for our target AI and RAG users.
2.  **Deprecate `beaver.Model`:** Our custom, incomplete `beaver.Model` will be removed.
3.  **Preserve Schemaless-First API:** For `DictManager`, `ListManager`, `QueueManager`, `LogManager`, `ChannelManager`, and `BlobManager`, the `model` parameter will remain **optional**.
    * **If `model=None` (default):** The managers will store raw, JSON-serializable Python objects (`dict`, `str`, `int`), preserving the simple, schemaless API.
    * **If `model=MyModel` (opt-in):** The managers will use Pydantic's robust `model_dump_json` and `model_validate_json` methods for full, recursive (de)serialization and validation.
4.  **Refactor `Document` and `CollectionManager`:** This is the core of the new design.
    * `Document` will be refactored to inherit from `pydantic.BaseModel` and become a generic class, `Document[M]`.
    * `Document[M]` will have three fixed fields: `id: str`, `embedding: Optional[list[float]]`, and `metadata: M`.
    * `CollectionManager` will also become generic, `CollectionManager[M]`.
    * `db.collection(model=MyModel)` will now define the type `M` for the `metadata` field, not the entire document.
    * **Hide `numpy`:** The user will *only* interact with `list[float]` in the `Document` model. The `CollectionManager` will be responsible for the internal conversion to/from `np.ndarray` before communicating with the `VectorIndex`.

### 2. Justification

This approach provides the best of all worlds:
* **Fixes the Bug:** It solves the recursive deserialization problem from Issue #9 by using Pydantic, a battle-tested library.
* **Simplifies the Codebase:** It allows us to delete our custom `beaver.Model` and `_ModelEncoder` and massively simplify the boilerplate-heavy `Document` class.
* **Improves Developer Experience:** Users get a choice. They can continue to use simple, schemaless dictionaries and lists, *or* opt-in to a best-in-class, fully-recursive type-safety system with Pydantic.
* **Improves API Cleanliness:** It abstracts away `numpy` as a pure implementation detail of the `CollectionManager`, providing a cleaner, user-facing API that only uses standard Python types (`list[float]`).

### 3. API Breaking Changes

This is a significant but highly beneficial breaking change.

* **`Document` Structure:** All custom user data must now be nested inside the `metadata` field.
    * **Before:** `Document(id="doc1", content="My text", author="Bob")`
    * **After:** `Document(id="doc1", metadata={"content": "My text", "author": "Bob"})`
* **`db.collection()` Factory:** The `model` parameter now defines the type of the `metadata` field.
    * **Before:** `db.collection(model=MyDocModel)` where `MyDocModel` inherited from `Document`.
    * **After:** `db.collection(model=MyMetaModel)` where `MyMetaModel` inherits from `pydantic.BaseModel` and represents the data *inside* `metadata`.
* **`numpy` Hidden:** Users who previously provided `np.ndarray` to the `Document` constructor must now provide a standard `list[float]`.

### 4. High-Level Roadmap

1.  **Dependencies (`pyproject.toml`):**
    * Add `pydantic` to the `[project.dependencies]`.
    * Ensure `numpy` is in `[project.optional-dependencies].vector` (it will be required by `beaver/collections.py` but is not a core dependency).

2.  **Types (`beaver/types.py`):**
    * Delete the `beaver.Model` class and `_ModelEncoder`.
    * Remove the `JsonSerializable` protocol.

3.  **Managers (`dicts.py`, `lists.py`, `queues.py`, `logs.py`, `channels.py`, `blobs.py`):**
    * Implement the conditional (de)serialization logic:
        * `_serialize`: Check if `self._model` is set (and not `dict`) and if `value` is a `BaseModel`. If yes, use `model_dump_json()`. Else, use `json.dumps()`.
        * `_deserialize`: Check if `self._model` is set (and not `dict`). If yes, use `self._model.model_validate_json()`. Else, use `json.loads()`.

4.  **Collections (`beaver/collections.py`):**
    * Import `Generic`, `TypeVar`, `BaseModel`, `Field`, etc., from Pydantic.
    * Redefine `Document` as `class Document(BaseModel, Generic[M]):` with fields `id`, `embedding: Optional[list[float]]`, and `metadata: M`.
    * Redefine `CollectionManager` as `class CollectionManager(Generic[M]):`.
    * Update `CollectionManager.__init__` to set `self._model = model or dict`.
    * Update `CollectionManager.index`:
        * It receives a `Document[M]`.
        * It serializes `document.metadata` to JSON (using `model_dump_json` if `metadata` is a `BaseModel`, else `json.dumps`).
        * It converts `document.embedding` (a `list[float]`) to `np.ndarray` *internally*.
        * It passes the `np.ndarray` to `self._vector_index.index()`.
    * Update `CollectionManager.__iter__`, `search`, and `match`:
        * These methods will fetch the raw `metadata` JSON and vector bytes.
        * They will deserialize the metadata using `self._model.model_validate()` (if `self._model` is not `dict`) or `json.loads()` (if it is).
        * They will convert the vector bytes (using `np.frombuffer`) into a `list[float]` (`.tolist()`).
        * They will construct and yield/return `Document[M]` instances with the `list[float]` embedding, hiding `numpy` completely from the user.

5.  **Core (`beaver/core.py`):**
    * Update the `db.collection` factory method to be generic (`def collection[M]...`) and correctly instantiate `CollectionManager[M]`.

6.  **Documentation & Examples:**
    * Update the `README.md` and all examples (`vector.py`, `fts.py`, `graph.py`, `type_hints.py`) to reflect the new `Document(metadata={...})` API.
    * Update the "Type-Safe Data Models" section of the `README.md` to explain the new Pydantic-first approach.
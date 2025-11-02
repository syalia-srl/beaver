---
number: 18
title: Enhanced `dump` and `load` for ETL
---

### 1. Feature Concept

This feature introduces a new `.load()` method to all primary data managers, creating a complete backup-and-restore capability to complement the existing `.dump()` method from **Issue #12**.

This plan also enhances both `.dump()` and `.load()` to support multiple serialization formats, each with a distinct purpose:
1.  **JSON (Full Backup):** The default format. Dumps/loads a single JSON object containing both `metadata` and an `items` list. This is best for full, faithful backups.
2.  **YAML (Full Backup):** A human-readable alternative to JSON. Dumps/loads the same `metadata` and `items` structure. This will be an optional feature.
3.  **JSONL (Items-Only Stream):** A memory-efficient, streaming format. Both `.dump()` and `.load()` will process the file one line at a time, never loading the entire dataset into memory. This format **omits the `metadata` block** and is ideal for data ingestion, export, and interoperability with other systems.

### 2. Use Cases

* **Full Backup & Restore:** A user can create a full, metadata-inclusive snapshot of a `CollectionManager` with `dump(f, format="json")` and restore it perfectly with `load(f, format="json")`.
* **Human-Readable Config:** A `DictManager` used for configuration can be dumped as a `.yaml` file, manually edited, and then loaded back into the application.
* **Large-Scale Data Ingestion:** A user can stream a 10GB JSONL file containing millions of log entries and load it directly into a `LogManager` using `load(f, format="jsonl")`. The memory usage will remain minimal as each line is processed and inserted individually.
* **Large-Scale Data Export:** A user can dump a `CollectionManager` with millions of documents to a JSONL file for use in an external data pipeline. The dump will stream directly from the database to the file, using very little memory.

### 3. API & Implementation Details

#### A. Dependencies

* To support the `yaml` format, `pyyaml` will be added as an **optional dependency** in `pyproject.toml` under a new extra, e.g., `yaml = ["pyyaml"]`. This aligns with the "Minimal & Optional Dependencies" principle.

#### B. Core Library API

**1. `dump()` Method Signature (Enhanced)**

The existing `.dump()` method (from **Issue #12**) will be enhanced to accept a `format` argument. The `fp=None` behavior (returning a `dict`) will only be supported for `format="json"`.

`dump(self, fp: IO[str] | None = None, format: str = "json", indent: int = 2) -> dict | None:`

* **`fp`:** The file-like object. If `None`, returns a Python `dict` (only if `format="json"`).
* **`format`:** A string, either `"json"`, `"yaml"`, or `"jsonl"`.
* **`indent`:** Applies to `"json"` and `"yaml"` formats for pretty-printing.

**2. `load()` Method Signature (New)**

A new `.load()` method will be added to all six data managers:

`load(self, fp: IO[str], format: str = "json", strategy: str = "overwrite") -> None:`

* **`fp`:** A file-like object opened in text read mode.
* **`format`:** A string, either `"json"`, `"yaml"`, or `"jsonl"`.
* **`strategy`:**
    * `"overwrite"` (default): Atomically calls `self.clear()` (from the previous feature plan) on the manager before loading any new items.
    * `"append"`: Appends the loaded items to the existing data. For `DictManager`, this will update/add keys.

#### C. Format-Handling Logic (Streaming-Aware)

**`dump()` Implementation:**

1.  **`format="json"`:**
    * If `fp` is `None`: Call `_get_dump_object()` and return the `dict`.
    * If `fp` is provided: Call `_get_dump_object()` and use `json.dump(dump_object, fp, indent=indent)`. (Not streaming).
2.  **`format="yaml"`:**
    * Requires `fp`. Import `yaml` (with `try...except`).
    * Call `_get_dump_object()` and use `yaml.dump(dump_object, fp, indent=indent)`. (Not streaming).
3.  **`format="jsonl"` (Streaming Dump):**
    * Requires `fp`. Do **not** call `_get_dump_object()`.
    * Iterate directly over the manager's items (e.g., `for item in self:` or `for k, v in self.items():`).
    * Inside the loop, format each `item` into its JSONL dictionary representation (e.g., `{"key": k, "value": v}` for dicts) and write `json.dumps(item_dict) + "\n"` to the stream `fp`.

**`load()` Implementation:**

1.  **`strategy` Handling:** Check `strategy` first. If `"overwrite"`, call `self.clear()` before doing anything else.
2.  **`format="json"` / `"yaml"` (Not streaming):**
    * Parse the entire file: `data = json.load(fp)` or `data = yaml.safe_load(fp)`.
    * Extract the `items = data["items"]` list.
    * Iterate through this `items` list and call a new private `_load_item(item)` helper for each one.
3.  **`format="jsonl"` (Streaming Load):**
    * Do **not** read the whole file.
    * Iterate *directly over the file object `fp` line by line*: `for line in fp:`.
    * Inside the loop, parse the single line: `item = json.loads(line)`.
    * Call the private `_load_item(item)` helper for that single item.
    * This ensures memory usage remains minimal, regardless of file size.

**`_load_item(item)` Helper:**

Each manager will have a private helper to handle inserting a single item `dict`:
* **`DictManager`:** `self.set(item["key"], item["value"])`
* **`ListManager`:** `self.push(item)` (Assumes JSONL items are the values themselves).
* **`QueueManager`:** `self.put(item["data"], priority=item["priority"])`
* **`LogManager`:** `self.log(item["data"], timestamp=datetime.fromtimestamp(item["timestamp"]))`
* **`BlobManager`:** `data = base64.b64decode(item["data_b64"])`; `self.put(item["key"], data, item["metadata"])`
* **`CollectionManager`:** `doc = Document(...)`; `self.index(doc)` (Reconstructs the `Document` from the `item` dict).

### 4. High-Level Roadmap

1.  **Phase 1: Dependencies**
    * Add `pyyaml` to `pyproject.toml` under a new optional dependency group: `[project.optional-dependencies] yaml = ["pyyaml"]`.

2.  **Phase 2: Enhance `.dump()` Method**
    * Refactor the `.dump()` method in all six managers to accept the `format` argument.
    * Implement the `if/elif` logic:
        * `"json"` / `"yaml"`: Use the existing `_get_dump_object()` flow.
        * `"jsonl"`: Implement the new **streaming** logic (iterating `self` and writing lines).

3.  **Phase 3: Implement `.load()` and `_load_item()` Methods**
    * Add the new `load(self, fp, format, strategy)` method to all six managers.
    * Add the private `_load_item(self, item)` helper method to each manager to encapsulate its specific insertion logic.
    * Implement the `load` method's `strategy` logic (`.clear()`).
    * Implement the `load` method's `format` logic, ensuring:
        * `"json"` and `"yaml"` parse the full file first, then iterate the *in-memory* list.
        * `"jsonl"` iterates *directly over the `fp` stream* line by line.

4.  **Phase 4: CLI & Documentation**
    * Update the `beaver dump` CLI command (from **Issue #14**) to accept a `--format [json|yaml|jsonl]` option.
    * Create the new `beaver load` CLI command (for **Issue #15**) using these methods, including `--format` and `--strategy [overwrite|append]` options.
    * Update all documentation (`README.md`, etc.) to advertise the new `.load()` method and the multi-format (especially JSONL streaming) capabilities.
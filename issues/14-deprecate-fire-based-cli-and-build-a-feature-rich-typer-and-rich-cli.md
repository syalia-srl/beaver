---
number: 14
title: "Deprecate `fire`-based CLI and build a feature-rich `typer` and `rich` CLI"
state: closed
labels:
---

### 1. Justification

The current `beaver client` command is a thin wrapper that uses `python-fire` to directly expose the methods of the `BeaverDB` object. While this was simple to implement, it provides a poor developer experience for several reasons:

  * **Low-Level Interface:** It's method-centric, not user-centric. A user must know the exact Python method and signature (e.g., `db.dict("name").set("key", "value")`) rather than a friendly command (`beaver dict set <name> <key> <value>`).
  * **Poor Output:** It returns raw Python object representations or simple strings, not well-formatted, human-readable output like tables or pretty-printed JSON.
  * **No Interactivity:** It is incapable of handling stateful or blocking operations, which are some of BeaverDB's most powerful features (e.g., `db.log().live()`, `db.channel().subscribe()`).
  * **Limited Shell Integration:** It's difficult to use for complex scripting, such as piping file contents to a blob or wrapping a shell command in a database lock.

This feature proposes **deprecating and removing `python-fire`** entirely. We will replace the `beaver client` command with a full-featured, custom-built CLI using `typer` (which we already use for `serve`) and `rich` (already used for errors).

### 2. Alignment with Philosophy

This refactor strongly supports our guiding principles:

  * **Simplicity and Pythonic API:** This extends "simplicity" to the terminal. A good CLI abstracts away internal method calls into intuitive, task-oriented commands.
  * **Developer Experience:** This is a massive improvement to the developer experience, making BeaverDB far more useful for administration, debugging, and shell scripting.
  * **Minimal & Optional Dependencies:** We will remove the `fire` dependency and replace it with `rich`, which is already a `typer` dependency, resulting in a cleaner and more powerful `[cli]` extra.

### 3. Proposed Command Structure

The `beaver client` sub-command will be removed. The main `beaver` app will host the data commands directly. All commands that output data will use `rich` for formatting (e.g., `rich.print_json`, `rich.table.Table`).

```sh
# The database path will be a top-level option, e.g.:
# beaver --database my.db <command>

# --- Dicts ---
# Get a value, pretty-print JSON if it's a structure
beaver dict <name> get <key>
# Set a value (with JSON parsing for values starting with { or [)
beaver dict <name> set <key> <value>
# Delete a key
beaver dict <name> del <key>
# List all keys
beaver dict <name> keys
# Dump the whole dictionary as JSON
beaver dict <name> dump

# --- Lists ---
beaver list <name> push <value>
beaver list <name> pop
beaver list <name> deque
beaver list <name> show # Renders the list in a rich.table
beaver list <name> dump

# --- Queues ---
beaver queue <name> put <priority> <value>
beaver queue <name> get --timeout 5 --block # Get an item
beaver queue <name> peek # View next item without popping
beaver queue <name> show # Renders queue in a rich.table

# --- Channels (Interactive) ---
beaver channel <name> publish <message>
beaver channel <name> listen # Runs a live loop printing messages

# --- Logs (Interactive) ---
beaver log <name> write <json_data>
beaver log <name> tail --window 30s # Runs a live loop printing aggregated data

# --- Blobs (File I/O) ---
beaver blob <store> put <key> <file_path> # Read from file
beaver blob <store> get <key> <output_file_path> # Write to file
beaver blob <store> del <key>
beaver blob <store> list # List all blob keys

# --- Collections ---
beaver collection <name> index <json_or_file_path> # Index a new document
beaver collection <name> drop <doc_id>
beaver collection <name> match <query> --on "field" --fuzzy 2
beaver collection <name> search <vector_json>
beaver collection <name> connect <source_id> <target_id> <label>

# --- Locks (Shell Integration) ---
# Wraps an arbitrary shell command in a BeaverDB lock
beaver lock <lock_name> --timeout 10 -- bash -c "run_script.sh"
```

### 4. High-Level Roadmap

1.  **Phase 1: Foundation & Dependency Swap**

      * Update `pyproject.toml`: Remove `fire` from `[project.optional-dependencies].cli`. Add `rich` as a dependency for the `cli` extra.
      * Refactor `beaver/cli.py`: Remove the `client` command, the `fire` import, and the `context_settings` that allowed `fire` to work.
      * Create new files (`beaver/cli/dict_commands.py`, `beaver/cli/list_commands.py`, etc.) and register them with the main `typer` app.
      * Add a global `db` instance that is initialized from the `--database` option.

2.  **Phase 2: Stateless "CRUD" Commands**

      * Implement the simple, stateless commands: `dict get/set/del/keys`, `list push/pop/deque`, `queue put/peek`, `channel publish`, `log write`.
      * Implement `dict dump` and `list dump` using the new `.dump()` methods.
      * Use `rich.print()` and `rich.print_json()` for all output.

3.  **Phase 3: File I/O Commands**

      * Implement `blob put` (reading from a `typer.Argument` path) and `blob get` (writing to a `typer.Argument` path).
      * Implement `collection index` to optionally read `Document` JSON from a file.

4.  **Phase 4: Stateful & Interactive Commands**

      * Implement `channel listen` by creating a loop that calls `listener.listen()` and prints new messages.
      * Implement `log tail` by iterating over the `logs.live()` generator and using `rich.Live` to update a table in place.
      * Implement `queue get --block`.

5.  **Phase 5: Shell Integration (`lock`)**

      * Implement the `beaver lock` command. This command will need to use `typer.Context` and `ctx.args` to capture the raw command to be executed.
      * The command logic will wrap a `subprocess.run(command_args)` call inside a `with db.lock(...):` block.
      * The exit code of the subprocess will be propagated as the exit code of the `beaver` command.
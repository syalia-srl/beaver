---
number: 15
title: "Enhance CLI with admin commands, shell piping, and interactivity"
state: open
labels:
- enhancement
---

### 1. Justification

The new `typer`-based CLI (from Issue #14) provides a robust, command-based interface for all of BeaverDB's data structures. However, to elevate it from a simple 1-to-1 method wrapper to a truly powerful administrative and scripting tool, it needs to embrace the shell and provide higher-level administrative commands.

This feature plan outlines a set of enhancements focused on:

1. **Shell Composability (Piping):** Allowing `beaver` to be a good "Unix citizen" by reading from `stdin` and writing raw data to `stdout`.
2. **Database-Wide Administration:** Providing top-level commands to get a summary of the database and perform bulk actions (like clearing a list).
3. **Usability:** Adding features like an interactive REPL and a "load" command to complement `dump` for backups.


### 2. Proposed Features & API

#### A. Shell & Unix Philosophy (Piping)

- **Read from `stdin`:** All commands that accept a value or file path (like `dict set`, `list push`, `blob put`, `collection index`) should accept a special `-` argument to read data from `stdin`.

```bash
# Pipe JSON to a dict key
echo '{"user": "admin", "level": 10}' | beaver dict config set site-admin -

# Pipe a file to a blob
cat my_avatar.png | beaver blob assets put user:123:avatar -
```

- **Raw Output (`--raw`):** All commands that print data (`dict get`, `list pop`, `list deque`, `list remove`, `queue get`, `blob get`, `collection get`) should have a `--raw` flag. This flag will suppress all `rich` formatting, labels, and success messages, and print _only_ the raw data. This is essential for piping the output to other tools like `jq`, `grep`, or even another `beaver` command.

```bash
# Get a raw JSON string and pipe it to jq
beaver dict config get site-admin --raw | jq .user

# Save a blob directly to a file
beaver blob assets get user:123:avatar --raw > new_avatar.png
```


#### B. Database-Wide Administration

- **`beaver info`:** A new top-level command that inspects the database and prints a summary "dashboard" of all data structures and their item counts.

```bash
$ beaver info

┌─────────────┬─────────────────┬───────┐
│ Type        │ Name            │ Count │
├─────────────┼─────────────────┼───────┤
│ Dict        │ config          │ 12    │
│ List        │ tasks           │ 110   │
│ Queue       │ agent_jobs      │ 45    │
│ Collection  │ articles        │ 1200  │
│ Blob Store  │ assets          │ 82    │
│ Log         │ system_metrics  │ 40592 │
│ Active Lock │ daily-cron-job  │ 1     │
└─────────────┴─────────────────┴───────┘
```

- **`clear` command:** A new subcommand for all data managers (`dict`, `list`, `queue`, `log`, `blob`, `collection`) to completely empty them.

```bash
# Clear all tasks from the queue
beaver queue agent_jobs clear

# Delete all documents from the collection
beaver collection articles clear
```

- **`beaver collection <name> compact`:** Expose the `.compact()` method to the CLI so a user can manually trigger a vector index compaction.

```bash
beaver collection articles compact --block
```


#### C. Enhanced Usability

- **`load` command:** The logical inverse of the `.dump()` command. This new subcommand for all managers would read a JSON file (in the format `dump` creates) and load its `items` into the data structure. This is critical for restoring backups.

```bash
beaver dict config load config_backup.json
```

- **`beaver repl`:** A new top-level command that opens an interactive read-evaluate-print loop (REPL). This would hold the database connection open and provide a `(beaver) >` prompt, allowing users to run commands without re-typing `beaver --database ...` each time.

```bash
$ beaver repl --database my.db
(beaver) > dict config get theme
dark
(beaver) > list tasks push "new interactive task"
Success: Item pushed to list 'tasks'.
(beaver) > exit
```

### 3. High-Level Roadmap

This can be implemented in logical phases:

1. **Phase 1: Admin Commands:** Implement `beaver info` and the `clear` subcommand for all data managers.
2. **Phase 2: Piping Output:** Add the `--raw` flag to all "getter" commands.
3. **Phase 3: Piping Input:** Add support for the `-` (stdin) argument on all "setter" commands.
4. **Phase 4: Backup/Restore:** Implement the `load` subcommand for all managers.
5. **Phase 5: Interactivity:** Implement the `beaver repl` command.
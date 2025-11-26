# Core Architecture

BeaverDB is built on a simple but powerful premise: **One File, Multiple Modalities.**

Instead of being a simple key-value store or a pure vector database, it acts as a "meta-database" that manages multiple specialized data structures (Dictionaries, Lists, Logs, Vectors) within a single SQLite file.

## The Facade Pattern

The entry point for the entire system is the `BeaverDB` class in `beaver.core`. It acts as a **Facade** and a **Resource Manager**.

* **Facade:** It provides factory methods (`.dict()`, `.list()`, `.collection()`) that hide the complexity of initializing specific managers.
* **Resource Manager:** It holds the persistent SQLite connection pool and manages thread safety.

### The Manager Pattern
BeaverDB does not implement data logic itself. Instead, it delegates to **Managers**.

When you call `db.dict("settings")`, BeaverDB:
1.  Checks its internal `_manager_cache` to see if a manager for "settings" already exists.
2.  If not, it initializes a `DictManager(name="settings", db=self)`.
3.  Returns the singleton instance.

This ensures that multiple calls to `db.dict("settings")` in the same process return the **same python object**, sharing locks and caches.

## Schema Design

BeaverDB uses a fixed set of internal tables to store user data. These tables are created automatically on initialization.

### Key-Value & Storage
| Table | Purpose | Schema |
| :--- | :--- | :--- |
| `beaver_dicts` | Stores all dictionaries | `dict_name, key, value, expires_at` |
| `beaver_lists` | Stores all lists | `list_name, item_order, item_value` |
| `beaver_blobs` | Stores binary files | `store_name, key, data, metadata` |
| `beaver_sketches` | Probabilistic structures | `name, type, config, data (BLOB)` |

### Search & Vectors
| Table | Purpose | Schema |
| :--- | :--- | :--- |
| `beaver_collections` | Main document storage | `collection, item_id, item_vector, metadata` |
| `beaver_fts_index` | Virtual table for Full-Text Search | `(FTS5 Virtual Table)` |
| `beaver_trigrams` | N-grams for fuzzy matching | `collection, trigram, item_id` |
| `beaver_edges` | Graph connections | `collection, source, target, label, weight` |

### Streams & Queues
| Table | Purpose | Schema |
| :--- | :--- | :--- |
| `beaver_logs` | Time-series logs | `log_name, timestamp, data` |
| `beaver_priority_queues` | Job queues | `queue_name, priority, timestamp, data` |
| `beaver_pubsub_log` | Message bus history | `channel_name, timestamp, message_payload` |

### System
| Table | Purpose | Schema |
| :--- | :--- | :--- |
| `beaver_lock_waiters` | Inter-process locks | `lock_name, waiter_id, expires_at` |

# Dictionaries (Key-Value Store)

BeaverDB provides a robust, persistent Key-Value store that behaves almost exactly like a standard Python dictionary. The `DictManager` allows you to store JSON-serializable data (strings, numbers, lists, dictionaries) that persists to disk and is safe to access across multiple processes.

This is the "Swiss Army Knife" for storing configuration, user sessions, application state, or caching API responses.

## Quick Start

Initialize a dictionary using `db.dict()`. If the dictionary doesn't exist, it is created automatically.

```python
from beaver import BeaverDB

db = BeaverDB("app.db")
settings = db.dict("app_settings")

# 1. Write data (Persists immediately to SQLite)
settings["theme"] = "dark"
settings["max_retries"] = 5
settings["features"] = {"beta": True, "logging": "verbose"}

# 2. Read data
print(settings["theme"])  # -> "dark"

# 3. Process-Safe
# You can open this same dict in another script/process safely.
```

## Basic Operations

### Getting and Setting Items

You can use standard bracket notation `[]` or the `.get()` method.

```python
# Set value
settings["user_1"] = {"name": "Alice", "score": 42}

# Get value (Raises KeyError if missing)
user = settings["user_1"]

# Get with default (Safe)
user = settings.get("user_99", default={"name": "Guest"})
```

### Checking Existence

Use the `in` operator to check if a key exists efficiently (O(1)).

```python
if "user_1" in settings:
    print("User exists!")
```

### Deleting Items

Remove items using `del` or `.pop()`.

```python
# Remove and return value
old_val = settings.pop("user_1", None)

# Delete key (Raises KeyError if missing)
del settings["max_retries"]

# Clear entire dictionary
settings.clear()
```

### Iteration

You can iterate over keys, values, or items just like a standard dict. Note that for very large dictionaries (millions of items), this streams data from the database to avoid loading everything into memory at once.

```python
for key in settings:
    print(key)

for key, val in settings.items():
    print(f"{key}: {val}")
```

## Advanced Features

### Time-To-Live (TTL)

You can set keys that automatically expire after a certain duration. This is perfect for caching or temporary session tokens.

```python
# Set a key that expires in 300 seconds (5 minutes)
settings.set("session_id", "xyz_123", ttl=300)

# Retrieving it after 5 minutes will return None (or raise KeyError)
```

### High-Performance Batching

If you need to insert thousands of items (e.g., an initial data migration or bulk import), inserting them one-by-one is slow because each write is a separate database transaction.

Use `.batched()` to buffer writes in memory and commit them in a single, high-speed transaction.

```python
# Insert 10,000 items efficiently
with settings.batched() as batch:
    for i in range(10000):
        batch[f"key_{i}"] = i
```

## Security & Encryption

BeaverDB offers a built-in **Security Suite** for Dictionaries, allowing you to store sensitive application secrets and user credentials securely.

### Encrypted Dictionaries (Secrets)

Pass a `secret` (passphrase) when initializing the dictionary. This enables **Encryption-at-Rest** using AES-128 (Fernet). The keys remain visible (for lookup speed), but the values are completely encrypted on disk.

```python
# Initialize securely
# If you lose the secret, the data is unrecoverable!
vault = db.dict("api_keys", secret="my-master-passphrase")

# Writes are encrypted before hitting the disk
vault["openai"] = "sk-..."

# Reads are automatically decrypted
print(vault["openai"])
```

### Secure Credentials (Hashing)

For user passwords or authentication tokens, you should never store the plain text (even if encrypted). Use the `Secret` wrapper to store a **One-Way Hash**.

BeaverDB automatically handles salting and PBKDF2 hashing for you.

```python
from beaver import Secret

users = db.dict("users", secret="master-key")

# Create a user with a hashed password
# The plain text "correct-horse" is hashed and discarded immediately.
users["alice"] = {
    "role": "admin",
    "password": Secret("correct-horse")
}

# Verify login
stored_user = users["alice"]
if stored_user["password"] == "correct-horse":
    print("Login Successful")
```

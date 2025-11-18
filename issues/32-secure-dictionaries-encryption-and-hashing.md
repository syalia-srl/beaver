---
number: 32
title: "Secure Dictionaries (Encryption and Hashing)"
state: open
labels:
---

### 1. Concept

This feature adds a comprehensive **Security Layer** to `DictManager`, addressing two critical needs:

1.  **Confidentiality (Encryption-at-Rest):** Storing sensitive recoverable data (API keys, PII) using transparent AES-128 encryption.
2.  **Verification (Secure Hashing):** Storing unrecoverable credentials (passwords) using a one-way `Secret[T]` wrapper.

It introduces a dedicated metadata table to handle salt storage and key validation securely, ensuring that a dictionary created with a secret cannot be opened without it.

### 2. Proposed API

#### A. Encrypted Dictionaries
Pass a `secret` to the factory method.

```python
# 1. Initialize
# The secret derives a 32-byte Fernet key.
# If the dictionary doesn't exist, it generates a random salt and stores it.
# If it does exist, it validates the secret against the stored verifier.
vault = db.dict("app_secrets", secret="my-master-passphrase")

# 2. Write
vault["github"] = "ghp_123..." # Encrypted on disk

# 3. Read
print(vault["github"]) # Automatically decrypted
```

#### B. The `Secret` Type

A value type for one-way hashing (e.g., passwords).

```python
from beaver import Secret

users = db.dict("users", secret="master-key")
# Stores only the hash and a unique salt for the password
users["alice"] = {"role": "admin", "password": Secret("correct-horse")}

if users["alice"]["password"] == "correct-horse":
    login()
```

### 3. Implementation Design

#### A. Schema (`beaver_dict_metadata`)

A new table stores security parameters, preventing metadata leakage into the main data table.

```sql
CREATE TABLE IF NOT EXISTS beaver_dict_metadata (
    dict_name TEXT PRIMARY KEY,
    salt TEXT NOT NULL,
    verifier TEXT NOT NULL,
    algo TEXT DEFAULT 'fernet-pbkdf2'
);
```

#### B. Cryptography Standards

  * **Dependency:** `cryptography` library (via `beaver-db[security]` extra).
  * **Encryption:** `Fernet` (AES-128 CBC + HMAC-SHA256).
  * **Key Derivation:** `PBKDF2HMAC` (SHA256) using the stored **Random Salt** (16 bytes).

#### C. `DictManager` Updates

1.  **`__init__`**: Performs the "Gatekeeper" logic (checking metadata table, validating secret via verifier decryption).
2.  **`__setitem__`**: Encrypts serialized JSON before INSERT.
3.  **`__getitem__`**: Decrypts bytes before JSON deserialization.
4.  **`update(other)`**: Enables re-keying by reading from `other` (decrypt) and writing to `self` (encrypt).

#### D. The `Secret[T]` Type

  * Inherits from `pydantic.BaseModel` (or similar) for automatic serialization support.
  * `__init__`: Hashes input, stores `(hash, salt)`, discards input.
  * `__eq__`: Verifies input against stored hash (constant-time).

### 4. Roadmap

1.  Add `cryptography` to `pyproject.toml`.
2.  Create `beaver/security.py` with `Cipher` (Encryption) and `Secret` (Hashing) classes.
3.  Add `_create_dict_metadata_table` to `BeaverDB.core`.
4.  Refactor `DictManager` to implement the security gatekeeper and I/O wrapping.
5.  Add tests for:
      * Data confidentiality (file inspection).
      * Invalid secret rejection.
      * Mixed plain/secure dictionary coexistence.
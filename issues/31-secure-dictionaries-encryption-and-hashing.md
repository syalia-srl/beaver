---
number: 31
title: "Secure Dictionaries (Encryption and Hashing)"
state: open
labels:
---

### 1. Concept

This feature adds a comprehensive **Security Layer** to `DictManager`, addressing two critical needs for modern local applications:

1.  **Confidentiality (Application Secrets):** Storing sensitive recoverable data (API keys, PII, config files) encrypted at rest.
    * **Solution:** A `secret` parameter for `db.dict()` that transparently encrypts the entire dictionary on disk using AES-128 (Fernet).

2.  **Verification (User Authentication):** Storing unrecoverable credentials (passwords, auth tokens) that should only ever be verified, never read back.
    * **Solution:** A generic `Secret[T]` type. Values wrapped in `Secret(...)` are automatically salted and hashed. The original value is discarded immediately, and the object only supports verification via equality checks (`==`).

### 2. Use Cases

* **Secrets Management:** Securely storing third-party API keys (`OPENAI_API_KEY`, `AWS_SECRET`) in a local configuration dictionary.
* **User Authentication:** Implementing a full user login system without boilerplate.

```python
  users = db.dict("users", secret="master-key")
  users["alice"] = {"role": "admin", "password": Secret("correct-horse")}

  if users["alice"]["password"] == "correct-horse":
      login()
```

### 3. Proposed API

#### A. Encrypted Dictionaries (Confidentiality)

Pass a `secret` to the factory method to enable transparent encryption for that specific dictionary.

```python
# 1. Initialize Vault
# The secret derives a 32-byte Fernet key.
vault = db.dict("app_secrets", secret="my-master-passphrase")

# 2. Write (Encrypted at rest)
# The entire JSON payload is encrypted before being written to SQLite.
# An attacker with the DB file sees only random bytes.
vault["github"] = {"token": "ghp_123...", "owner": "octocat"}

# 3. Read (Decrypted automatically)
# If the wrong secret was provided during init, this raises an error.
print(vault["github"]["token"])
```

#### B. The `Secret` Type (Verification)

Use the `Secret` wrapper for data that must be one-way hashed (like passwords). This works inside *any* dictionary, but is best used within an Encrypted Dictionary for defense-in-depth.

```python
from beaver import Secret

# 1. Store a Password
# Secret() generates a random 16-byte salt, computes a PBKDF2 hash,
# and discards the plaintext immediately.
users = db.dict("users", secret="master-key")
users["alice"] = {
    "email": "alice@example.com",
    "credentials": Secret("user-password-123")
}

# 2. Verify
# Retrieve the object (which contains only salt + hash).
stored_creds = users["alice"]["credentials"]

# The __eq__ operator re-hashes the right-hand side using the stored salt
# and compares them using a constant-time algorithm.
if stored_creds == "user-password-123":
    print("Login Successful")
else:
    print("Invalid Password")

# 3. Safety
# Attempting to access the value fails, as it was never stored.
```

### 4. Implementation Design

#### A. Dependencies

  * **Extra:** `beaver-db[security]` adds the `cryptography` library.
  * **Encryption:** **Fernet** (AES-128 CBC + HMAC-SHA256).
  * **Hashing:** **PBKDF2-HMAC-SHA256** (600,000 iterations).

#### B. The `Secret[T]` Type

This class will be designed to integrate seamlessly with Pydantic's serialization engine.

  * **State:** Stores `salt` (bytes) and `hash` (bytes).
  * **Initialization:**
      * `Secret("plain_text")`: Generates salt -> Computes Hash -> Stores `(salt, hash)`.
  * **Serialization:**
      * Handled automatically by Pydantic.
  * **Comparison (`__eq__`):**
      * `self == candidate`: Computes `Hash(candidate, self.salt)` and compares with `self.hash` using `hmac.compare_digest`.

#### C. `DictManager` Integration

The `DictManager` will wrap its I/O methods if `secret` is present.

  * **Key Derivation:** Use `KBKDF2HMAC` with a deterministic salt (SHA-256 hash of the dictionary name) to turn the user's `secret` string into a valid 32-byte Fernet key.
  * **Write Path (`__setitem__`):**
    1.  Serialize data to JSON (handling `Secret` objects via standard rules).
    2.  Encrypt JSON bytes using Fernet.
    3.  Store encrypted base64 string in SQLite.
  * **Read Path (`__getitem__`):**
    1.  Read string from SQLite.
    2.  Decrypt using Fernet.
    3.  Deserialize JSON (reconstructing `Secret` objects from their dict representation).

### 5. Roadmap

1.  Add `cryptography` to `pyproject.toml`.
2.  Implement `beaver.security.Cipher` helper (Key derivation + Fernet).
3.  Implement `beaver.security.Secret[T]` class.
4.  Update `BeaverDB.dict()` factory to accept `secret`.
5.  Update `DictManager` to use `Cipher` for read/write operations.
6.  Add tests:
      * Verify `Secret("pw") == "pw"`.
      * Verify `Secret("pw") != "wrong"`.
      * Verify data on disk is encrypted (by inspecting the raw SQLite file).
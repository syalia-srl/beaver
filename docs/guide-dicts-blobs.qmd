# Key-Value and Blob Storage

**Chapter Outline:**

* **3.1. Dictionaries & Caching (`db.dict`)**
    * A Python-like dictionary interface: `config["api_key"] = ...`
    * Standard methods: `.get()`, `del`, `len()`, iterating with `.items()`.
    * **Use Case: Caching with TTL:** Using `.set(key, value, ttl_seconds=3600)`.
* **3.2. Blob Storage (`db.blobs`)**
    * Storing binary data (images, PDFs, files) with metadata.
    * API: `.put(key, data, metadata)`, `.get(key)`.
    * The `Blob` object: Accessing `.data` and `.metadata`.

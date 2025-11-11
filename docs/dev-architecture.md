# Core Architecture & Design

**Chapter Outline:**

* **9.1. Guiding Principles (Developer Focus)**
    * A deeper dive into the "Why" from `design.md`.
    * Standard SQLite Compatibility as a "no-magic" rule.
    * Convention over Configuration.
* **9.2. The Manager Delegation Pattern**
    * How `BeaverDB` acts as a factory.
    * How managers (e.g., `DictManager`) are initialized with a reference to the core `BeaverDB` connection pool.
    * How all tables are prefixed with `beaver_` to avoid user-space conflicts.
* **9.3. Type-Safe Models (`beaver.Model`)**
    * Using the `model=...` parameter for automatic serialization and deserialization.
    * Inheriting from `beaver.Model` for a lightweight, Pydantic-compatible solution.

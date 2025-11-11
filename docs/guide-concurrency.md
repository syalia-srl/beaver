# Concurrency

**Chapter Outline:**

* **7.1. Inter-Process Locks (`db.lock`)**
    * Creating a critical section: `with db.lock("my_task", timeout=10): ...`
    * Guarantees: Fair (FIFO) and Deadlock-Proof (via TTL).
* **7.2. Atomic Operations on Data Structures**
    * Locking a specific manager: `with db.dict("config") as config: ...`
    * **Use Case:** Atomically getting and processing a *batch* of items from a queue.

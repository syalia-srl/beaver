# Lists and Queues

**Chapter Outline:**

* **4.1. Persistent Lists (`db.list`)**
    * A full-featured, persistent Python list.
    * Full support for: `push`, `pop`, `prepend`, `deque`, slicing `my_list[1:5]`, and in-place updates `my_list[0] = ...`.
* **4.2. Priority Queues (`db.queue`)**
    * Creating a persistent, multi-process task queue.
    * Adding tasks: `.put(data, priority=N)` (lower number is higher priority).
    * Consuming tasks: The blocking `.get(timeout=N)` method.
    * **Use Case:** A multi-process producer/consumer pattern.

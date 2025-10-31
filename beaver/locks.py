import random
import time
import os
import uuid
from typing import Optional
from .types import IDatabase


class LockManager:
    """
    An inter-process, deadlock-proof, and fair (FIFO) lock built on SQLite.

    This class provides a context manager (`with` statement) to ensure that
    only one process (among many) can enter a critical section of code at a
    time.

    It is "fair" because it uses a FIFO queue (based on insertion time).
    It is "deadlock-proof" because locks have a Time-To-Live (TTL); if a
    process crashes, its lock will eventually expire and be cleaned up.
    """

    def __init__(
        self,
        db: IDatabase,
        name: str,
        timeout: Optional[float] = None,
        lock_ttl: float = 60.0,
        poll_interval: float = 0.1,
    ):
        """
        Initializes the lock manager.

        Args:
            db: The BeaverDB instance.
            name: The unique name of the lock (e.g., "run_compaction").
            timeout: Max seconds to wait to acquire the lock. If None,
                     it will wait forever.
            lock_ttl: Max seconds the lock can be held. If the process crashes,
                      the lock will auto-expire after this time.
            poll_interval: Seconds to wait between polls.
        """
        if not isinstance(name, str) or not name:
            raise ValueError("Lock name must be a non-empty string.")
        if lock_ttl <= 0:
            raise ValueError("lock_ttl must be positive.")
        if poll_interval <= 0:
            raise ValueError("poll_interval must be positive.")

        self._db = db
        self._lock_name = name
        self._timeout = timeout
        self._lock_ttl = lock_ttl
        self._poll_interval = poll_interval
        # A unique ID for this specific lock instance across all processes
        self._waiter_id = f"pid:{os.getpid()}:id:{uuid.uuid4()}"
        self._acquired = False  # State to track if this instance holds the lock

    def acquire(self,
                timeout: float|None = None,
        lock_ttl: float |None = None,
        poll_interval: float |None = None,
        ) -> "LockManager":
        """
        Blocks until the lock is acquired or the timeout expires.

        Raises:
            TimeoutError: If the lock cannot be acquired within the specified timeout.
        """
        if self._acquired:
            # This instance already holds the lock
            return self

        if timeout is None:
            timeout = self._timeout

        if lock_ttl is None:
            lock_ttl = self._lock_ttl

        if poll_interval is None:
            poll_interval = self._poll_interval

        start_time = time.time()
        requested_at = time.time()
        expires_at = requested_at + lock_ttl

        conn = self._db.connection

        try:
            # 1. Add self to the FIFO queue (atomic)
            with conn:
                conn.execute(
                    """
                    INSERT INTO beaver_lock_waiters (lock_name, waiter_id, requested_at, expires_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (self._lock_name, self._waiter_id, requested_at, expires_at),
                )

            # 2. Start polling loop
            while True:
                with conn:
                    # 3. Clean up expired locks from crashed processes
                    now = time.time()
                    conn.execute(
                        "DELETE FROM beaver_lock_waiters WHERE lock_name = ? AND expires_at < ?",
                        (self._lock_name, now),
                    )

                    # 4. Check who is at the front of the queue
                    cursor = conn.cursor()
                    cursor.execute(
                        """
                        SELECT waiter_id FROM beaver_lock_waiters
                        WHERE lock_name = ?
                        ORDER BY requested_at ASC
                        LIMIT 1
                        """,
                        (self._lock_name,),
                    )
                    result = cursor.fetchone()
                    cursor.close()

                    if result and result["waiter_id"] == self._waiter_id:
                        # We are at the front. We own the lock.
                        self._acquired = True
                        return self

                # 5. Check for timeout
                if timeout is not None:
                    if (time.time() - start_time) > timeout:
                        # We timed out. Remove ourselves from the queue and raise.
                        self._release_from_queue()
                        raise TimeoutError(
                            f"Failed to acquire lock '{self._lock_name}' within {timeout}s."
                        )

                # 6. Wait politely before polling again
                # Add +/- 10% jitter to the poll interval to avoid thundering herd
                jitter = poll_interval * 0.1
                sleep_time = random.uniform(
                    poll_interval - jitter, poll_interval + jitter
                )
                time.sleep(sleep_time)

        except Exception:
            # If anything goes wrong, try to clean up our waiter entry
            self._release_from_queue()
            raise

    def _release_from_queue(self):
        """
        Atomically removes this instance's entry from the waiter queue.
        This is a best-effort, fire-and-forget operation.
        """
        try:
            with self._db.connection:
                self._db.connection.execute(
                    "DELETE FROM beaver_lock_waiters WHERE lock_name = ? AND waiter_id = ?",
                    (self._lock_name, self._waiter_id),
                )
        except Exception:
            # Don't raise errors during release/cleanup
            pass

    def release(self):
        """
        Releases the lock, allowing the next process in the queue to acquire it.
        This is safe to call multiple times.
        """
        if not self._acquired:
            # We don't hold the lock, so nothing to do.
            return

        self._release_from_queue()
        self._acquired = False

    def __enter__(self) -> "LockManager":
        """Acquires the lock when entering a 'with' statement."""
        return self.acquire()

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Releases the lock when exiting a 'with' statement."""
        self.release()

    def __repr__(self) -> str:
        return f"LockManager(name='{self._lock_name}', acquired={self._acquired})"

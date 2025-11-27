import asyncio
import random
import time
import os
import uuid
from typing import Optional, Protocol, runtime_checkable

# We use a forward reference for the DB to avoid circular imports
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .core import AsyncBeaverDB


@runtime_checkable
class IBeaverLock(Protocol):
    """
    The Synchronous Protocol that BeaverBridge exposes to the user.
    """

    def acquire(
        self,
        timeout: float | None = None,
        lock_ttl: float | None = None,
        poll_interval: float | None = None,
        block: bool = True,
    ) -> bool: ...

    def release(self) -> None: ...
    def renew(self, lock_ttl: float | None = None) -> bool: ...
    def clear(self) -> bool: ...
    def __enter__(self) -> "IBeaverLock": ...
    def __exit__(self, exc_type, exc_val, exc_tb) -> None: ...


class AsyncBeaverLock:
    """
    An inter-process, deadlock-proof, and fair (FIFO) lock built on SQLite.

    This Async version runs on the event loop, using non-blocking sleeps
    and atomic transactions to coordinate access safely across processes.
    """

    def __init__(
        self,
        db: "AsyncBeaverDB",
        name: str,
        timeout: Optional[float] = None,
        lock_ttl: float = 60.0,
        poll_interval: float = 0.1,
    ):
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

        # Unique ID for this specific lock instance
        self._waiter_id = f"pid:{os.getpid()}:id:{uuid.uuid4()}"
        self._acquired = False

    async def renew(self, lock_ttl: Optional[float] = None) -> bool:
        """
        Renews the TTL (heartbeat) of the lock held by this instance.
        """
        if not self._acquired:
            return False

        ttl = lock_ttl or self._lock_ttl
        if ttl <= 0:
            raise ValueError("lock_ttl must be positive.")

        new_expires_at = time.time() + ttl

        # Simple update, no need for full transaction lock if we already hold it logically,
        # but using transaction() is safer to avoid interleaving issues.
        async with self._db.transaction():
            cursor = await self._db.connection.execute(
                "UPDATE __beaver_lock_waiters__ SET expires_at = ? WHERE lock_name = ? AND waiter_id = ?",
                (new_expires_at, self._lock_name, self._waiter_id),
            )
            return cursor.rowcount > 0

    async def clear(self) -> bool:
        """
        Forcibly removes ALL waiters for this lock.
        """
        async with self._db.transaction():
            cursor = await self._db.connection.execute(
                "DELETE FROM __beaver_lock_waiters__ WHERE lock_name = ?",
                (self._lock_name,),
            )
            count = cursor.rowcount

        self._acquired = False
        return count > 0

    async def acquire(
        self,
        timeout: float | None = None,
        lock_ttl: float | None = None,
        poll_interval: float | None = None,
        block: bool = True,
    ) -> bool:
        """
        Attempts to acquire the lock.
        """
        if self._acquired:
            return True

        current_timeout = timeout if timeout is not None else self._timeout
        current_lock_ttl = lock_ttl if lock_ttl is not None else self._lock_ttl
        current_poll_interval = (
            poll_interval if poll_interval is not None else self._poll_interval
        )

        start_time = time.time()
        requested_at = time.time()
        expires_at = requested_at + current_lock_ttl

        try:
            # 1. Add self to the FIFO queue (Atomic)
            # We use .transaction() to ensure no other task interleaves commands
            async with self._db.transaction():
                await self._db.connection.execute(
                    """
                    INSERT INTO __beaver_lock_waiters__
                    (lock_name, waiter_id, requested_at, expires_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (self._lock_name, self._waiter_id, requested_at, expires_at),
                )

            # 2. Start Polling Loop
            while True:
                async with self._db.transaction():
                    # A. Clean up expired locks from crashed processes
                    now = time.time()
                    await self._db.connection.execute(
                        "DELETE FROM __beaver_lock_waiters__ WHERE lock_name = ? AND expires_at < ?",
                        (self._lock_name, now),
                    )

                    # B. Check who is at the front of the queue
                    cursor = await self._db.connection.execute(
                        """
                        SELECT waiter_id FROM __beaver_lock_waiters__
                        WHERE lock_name = ?
                        ORDER BY requested_at ASC
                        LIMIT 1
                        """,
                        (self._lock_name,),
                    )
                    result = await cursor.fetchone()

                    if result and result["waiter_id"] == self._waiter_id:
                        # We are at the front. We own the lock.
                        self._acquired = True
                        return True

                # 3. Check for timeout or non-blocking return
                elapsed = time.time() - start_time

                if current_timeout is not None and elapsed > current_timeout:
                    await self._release_from_queue()
                    return False

                if not block:
                    await self._release_from_queue()
                    return False

                # 4. Wait safely (Yield to Event Loop)
                jitter = current_poll_interval * 0.1
                sleep_time = random.uniform(
                    current_poll_interval - jitter, current_poll_interval + jitter
                )
                await asyncio.sleep(sleep_time)

        except Exception:
            # If anything goes wrong, try to clean up our waiter entry
            await self._release_from_queue()
            raise

    async def _release_from_queue(self):
        """
        Atomically removes this instance's entry from the waiter queue.
        """
        try:
            async with self._db.transaction():
                await self._db.connection.execute(
                    "DELETE FROM __beaver_lock_waiters__ WHERE lock_name = ? AND waiter_id = ?",
                    (self._lock_name, self._waiter_id),
                )
        except Exception:
            pass

    async def release(self):
        """
        Releases the lock.
        """
        if not self._acquired:
            return

        await self._release_from_queue()
        self._acquired = False

    async def __aenter__(self) -> "AsyncBeaverLock":
        if await self.acquire():
            return self

        raise TimeoutError("Cannot acquire lock.")

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.release()

    def __repr__(self) -> str:
        return f"AsyncBeaverLock(name='{self._lock_name}', acquired={self._acquired})"

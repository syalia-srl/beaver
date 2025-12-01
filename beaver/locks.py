import asyncio
import random
import time
import os
import uuid
from typing import Optional, TYPE_CHECKING
from .interfaces import IAsyncBeaverLock


if TYPE_CHECKING:
    from .core import AsyncBeaverDB


class AsyncBeaverLock(IAsyncBeaverLock):
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
        self._db = db
        self._lock_name = name
        self._timeout = timeout
        self._lock_ttl = lock_ttl
        self._poll_interval = poll_interval
        self._waiter_id = f"pid:{os.getpid()}:id:{uuid.uuid4()}"
        self._acquired = False

    async def renew(self, lock_ttl: Optional[float] = None) -> bool:
        if not self._acquired:
            return False

        ttl = lock_ttl or self._lock_ttl
        new_expires_at = time.time() + ttl

        async with self._db.transaction():
            cursor = await self._db.connection.execute(
                "UPDATE __beaver_lock_waiters__ SET expires_at = ? WHERE lock_name = ? AND waiter_id = ?",
                (new_expires_at, self._lock_name, self._waiter_id),
            )
            return cursor.rowcount > 0

    async def clear(self) -> bool:
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
            # 1. Add self to the FIFO queue (Atomic via transaction() lock)
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
                        ORDER BY requested_at ASC, rowid ASC
                        LIMIT 1
                        """,
                        (self._lock_name,),
                    )
                    result = await cursor.fetchone()

                    # C. Sanity Check: Ensure we are still in the queue
                    check_self = await self._db.connection.execute(
                        "SELECT 1 FROM __beaver_lock_waiters__ WHERE waiter_id = ?",
                        (self._waiter_id,),
                    )
                    if not await check_self.fetchone():
                        return False  # We were deleted (cleared or expired)

                    if result and result["waiter_id"] == self._waiter_id:
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

                # 4. Wait safely
                jitter = current_poll_interval * 0.1
                sleep_time = random.uniform(
                    current_poll_interval - jitter, current_poll_interval + jitter
                )
                await asyncio.sleep(sleep_time)

        except Exception:
            await self._release_from_queue()
            raise

    async def _release_from_queue(self):
        try:
            async with self._db.transaction():
                await self._db.connection.execute(
                    "DELETE FROM __beaver_lock_waiters__ WHERE lock_name = ? AND waiter_id = ?",
                    (self._lock_name, self._waiter_id),
                )
        except Exception:
            pass

    async def release(self):
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

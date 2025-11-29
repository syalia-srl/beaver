import math
import hashlib
import struct
import asyncio
from typing import (
    Any,
    Iterator,
    Optional,
    Protocol,
    runtime_checkable,
    TYPE_CHECKING,
    Self,
)

from pydantic import BaseModel

from .manager import AsyncBeaverBase, atomic, emits
from .locks import AsyncBeaverLock

if TYPE_CHECKING:
    from .core import AsyncBeaverDB


def _calculate_hll_precision(error_rate: float) -> int:
    """Derives the HyperLogLog precision 'p' from a desired error rate."""
    if not (0 < error_rate < 1):
        raise ValueError("Error rate must be between 0 and 1")
    p = 2 * math.log2(1.04 / error_rate)
    return max(4, min(int(math.ceil(p)), 18))


def _calculate_bloom_params(capacity: int, error_rate: float) -> tuple[int, int]:
    """Calculates optimal Bloom Filter size (bits) and hash count (k)."""
    if capacity <= 0:
        raise ValueError("Capacity must be positive")
    if not (0 < error_rate < 1):
        raise ValueError("Error rate must be between 0 and 1")

    m_bits = -(capacity * math.log(error_rate)) / (math.log(2) ** 2)
    k = (m_bits / capacity) * math.log(2)
    return int(math.ceil(m_bits)), int(math.ceil(k))


class ApproximateSet:
    """
    A unified probabilistic data structure combining HyperLogLog and Bloom Filter.
    Pure Python implementation (CPU-bound).
    """

    def __init__(
        self,
        capacity: int = 1_000_000,
        error_rate: float = 0.01,
        data: bytes | None = None,
    ):
        self.capacity = capacity
        self.error_rate = error_rate

        # 1. Configure HyperLogLog
        self.p = _calculate_hll_precision(error_rate)
        self.m = 1 << self.p
        self.alpha = self._get_alpha(self.m)

        # 2. Configure Bloom Filter
        self.bloom_bits, self.bloom_k = _calculate_bloom_params(capacity, error_rate)
        self.bloom_bytes_len = (self.bloom_bits + 7) // 8

        # 3. Initialize or Load Storage
        expected_size = self.m + self.bloom_bytes_len

        if data:
            if len(data) != expected_size:
                raise ValueError(
                    f"Corrupted sketch data. Expected {expected_size} bytes, got {len(data)}"
                )
            self._data = bytearray(data)
        else:
            self._data = bytearray(expected_size)

    def _get_alpha(self, m: int) -> float:
        if m == 16:
            return 0.673
        elif m == 32:
            return 0.697
        elif m == 64:
            return 0.709
        return 0.7213 / (1 + 1.079 / m)

    def add(self, item_bytes: bytes):
        self._add_hll(item_bytes)
        self._add_bloom(item_bytes)

    def _add_hll(self, item_bytes: bytes):
        h = hashlib.sha1(item_bytes).digest()
        x = struct.unpack("<Q", h[:8])[0]
        j = x & (self.m - 1)
        w = x >> self.p
        rank = 1
        while w & 1 == 0 and rank <= (64 - self.p):
            rank += 1
            w >>= 1
        if rank > self._data[j]:
            self._data[j] = rank

    def _add_bloom(self, item_bytes: bytes):
        h = hashlib.md5(item_bytes).digest()
        h1, h2 = struct.unpack("<QQ", h)
        offset = self.m
        for i in range(self.bloom_k):
            bit_idx = (h1 + i * h2) % self.bloom_bits
            byte_idx = offset + (bit_idx // 8)
            mask = 1 << (bit_idx % 8)
            self._data[byte_idx] |= mask

    def __contains__(self, item_bytes: bytes) -> bool:
        h = hashlib.md5(item_bytes).digest()
        h1, h2 = struct.unpack("<QQ", h)
        offset = self.m
        for i in range(self.bloom_k):
            bit_idx = (h1 + i * h2) % self.bloom_bits
            byte_idx = offset + (bit_idx // 8)
            mask = 1 << (bit_idx % 8)
            if not (self._data[byte_idx] & mask):
                return False
        return True

    def __len__(self) -> int:
        zeros = 0
        sum_inv = 0.0
        for i in range(self.m):
            val = self._data[i]
            if val == 0:
                zeros += 1
            sum_inv += 2.0 ** (-val)
        E = self.alpha * (self.m**2) / sum_inv
        if E <= 2.5 * self.m:
            if zeros > 0:
                E = self.m * math.log(self.m / zeros)
        return int(E)

    def to_bytes(self) -> bytes:
        return bytes(self._data)


class AsyncSketchBatch[T: BaseModel]:
    """Async Context manager for batched updates to an ApproximateSet."""

    def __init__(self, manager: "AsyncBeaverSketch[T]"):
        self._manager = manager
        self._pending_items: list[Any] = []

    def add(self, item: Any):
        """Adds an item to the pending batch buffer."""
        self._pending_items.append(item)

    async def __aenter__(self):
        if self._manager._sketch is None:
            await self._manager._ensure_sketch()

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if not self._pending_items:
            return

        # Atomic Bulk Update: Lock -> Reload -> Modify -> Save
        async with self._manager._internal_lock:
            async with self._manager._db.transaction():
                # 1. Reload latest state from DB
                await self._manager._reload()

                # 2. Update in-memory (CPU bound, could offload to thread if huge)
                for item in self._pending_items:
                    serialized_item = self._manager._serialize(item)
                    item_bytes = serialized_item.encode("utf-8")
                    self._manager._sketch.add(item_bytes)

                # 3. Save back to DB
                await self._manager._save()

        self._pending_items.clear()


@runtime_checkable
class IBeaverSketch[T: BaseModel](Protocol):
    """Protocol exposed to the user via BeaverBridge."""

    def add(self, item: T) -> None: ...
    def contains(self, item: T) -> bool: ...
    def count(self) -> int: ...
    def clear(self) -> None: ...
    def batched(self) -> AsyncSketchBatch[T]: ...
    def __len__(self) -> int: ...
    def __contains__(self, item: T) -> bool: ...


class AsyncBeaverSketch[T: BaseModel](AsyncBeaverBase[T]):
    """
    Manages a persistent ApproximateSet (Bloom + HLL).
    """

    def __init__(
        self,
        name: str,
        db: "AsyncBeaverDB",
        capacity: int = 1_000_000,
        error_rate: float = 0.01,
        model: type[T] | None = None,
    ):
        super().__init__(name, db, model=model)
        self._capacity = capacity
        self._error_rate = error_rate
        self._sketch: ApproximateSet | None = None

    async def _ensure_sketch(self):
        """Loads the sketch from DB or creates it if it doesn't exist."""
        cursor = await self.connection.execute(
            "SELECT capacity, error_rate, data FROM __beaver_sketches__ WHERE name = ?",
            (self._name,),
        )
        row = await cursor.fetchone()

        if row:
            db_cap, db_err, db_data = row["capacity"], row["error_rate"], row["data"]
            # Allow small float tolerance
            if db_cap != self._capacity or abs(db_err - self._error_rate) > 1e-9:
                raise ValueError(
                    f"Sketch '{self._name}' exists with capacity={db_cap}, error={db_err}. "
                    f"Cannot load with requested capacity={self._capacity}, error={self._error_rate}."
                )
            self._sketch = ApproximateSet(
                self._capacity, self._error_rate, data=db_data
            )
        else:
            self._sketch = ApproximateSet(self._capacity, self._error_rate)
            await self._save()

    async def _reload(self):
        """Reloads the binary data from the database."""
        cursor = await self.connection.execute(
            "SELECT data FROM __beaver_sketches__ WHERE name = ?", (self._name,)
        )
        row = await cursor.fetchone()
        if row:
            self._sketch._data = bytearray(row["data"])

    async def _save(self):
        """Persists the current in-memory sketch to the database."""
        if self._sketch:
            await self.connection.execute(
                """
                INSERT OR REPLACE INTO __beaver_sketches__ (name, type, capacity, error_rate, data)
                VALUES (?, 'approx_set', ?, ?, ?)
                """,
                (self._name, self._capacity, self._error_rate, self._sketch.to_bytes()),
            )

    @atomic
    async def add(self, item: T):
        """
        Adds a single item to the sketch atomically.
        """
        if self._sketch is None:
            await self._ensure_sketch()

        serialized_item = self._serialize(item)
        item_bytes = serialized_item.encode("utf-8")

        await self._reload()
        self._sketch.add(item_bytes)
        await self._save()

    async def contains(self, item: T) -> bool:
        """
        Checks membership using the local cached state.
        Note: Does not strictly reload from DB for performance reasons.
        """
        if self._sketch is None:
            await self._ensure_sketch()

        serialized_item = self._serialize(item)
        item_bytes = serialized_item.encode("utf-8")
        return item_bytes in self._sketch

    async def count(self) -> int:
        """Returns approximate cardinality using local cached state."""
        if self._sketch is None:
            await self._ensure_sketch()

        return len(self._sketch)

    def batched(self) -> AsyncSketchBatch[T]:
        """Returns an async context manager for batched updates."""
        # Initialize lazily if needed
        if self._sketch is None:
            # We can't await here in a sync method, so we rely on _init or first usage
            pass

        return AsyncSketchBatch(self)

    async def clear(self):
        """Resets the sketch to empty."""
        if self._sketch is None:
            await self._ensure_sketch()

        self._sketch = ApproximateSet(self._capacity, self._error_rate)
        await self._save()

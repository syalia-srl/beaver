import math
import hashlib
import struct
import threading
from typing import Any, Iterator, Optional
from contextlib import contextmanager

from pydantic import BaseModel

from .manager import ManagerBase, synced
from .types import IDatabase


def _calculate_hll_precision(error_rate: float) -> int:
    """
    Derives the HyperLogLog precision 'p' from a desired error rate.
    Formula: error ≈ 1.04 / sqrt(2^p)
    """
    if not (0 < error_rate < 1):
        raise ValueError("Error rate must be between 0 and 1")

    # Calculate theoretical p
    p = 2 * math.log2(1.04 / error_rate)
    # Round to nearest integer and clamp to reasonable bounds (4 to 18)
    return max(4, min(int(math.ceil(p)), 18))


def _calculate_bloom_params(capacity: int, error_rate: float) -> tuple[int, int]:
    """
    Calculates optimal Bloom Filter size (bits) and hash count (k).
    """
    if capacity <= 0:
        raise ValueError("Capacity must be positive")
    if not (0 < error_rate < 1):
        raise ValueError("Error rate must be between 0 and 1")

    # m = - (n * ln(p)) / (ln(2)^2)
    m_bits = -(capacity * math.log(error_rate)) / (math.log(2) ** 2)

    # k = (m / n) * ln(2)
    k = (m_bits / capacity) * math.log(2)

    return int(math.ceil(m_bits)), int(math.ceil(k))


class ApproximateSet:
    """
    A unified probabilistic data structure combining HyperLogLog (cardinality)
    and Bloom Filter (membership) into a single binary block.
    """

    # HLL Constants
    HLL_ALPHA_INF = 0.7213 / (1 + 1.079 / (2**32))  # Approximation for large m

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
        self.m = 1 << self.p  # Number of registers (2^p)
        self.alpha = self._get_alpha(self.m)

        # 2. Configure Bloom Filter
        self.bloom_bits, self.bloom_k = _calculate_bloom_params(capacity, error_rate)
        # Round Bloom size up to nearest byte
        self.bloom_bytes_len = (self.bloom_bits + 7) // 8

        # 3. Initialize or Load Storage
        expected_size = self.m + self.bloom_bytes_len

        if data:
            if len(data) != expected_size:
                raise ValueError(f"Corrupted sketch data. Expected {expected_size} bytes, got {len(data)}")
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
        """Adds an item to both the HyperLogLog and Bloom Filter."""
        self._add_hll(item_bytes)
        self._add_bloom(item_bytes)

    def _add_hll(self, item_bytes: bytes):
        # Hash: SHA1 for HLL (consistent 160 bits)
        h = hashlib.sha1(item_bytes).digest()

        # Use first 64 bits (8 bytes) for HLL logic
        # In a real implementation we might need more bits for p>16, but standard is p=14
        x = struct.unpack("<Q", h[:8])[0]

        # Determine register index j (first p bits)
        j = x & (self.m - 1)

        # Determine rank (leading zeros in remaining bits)
        w = x >> self.p
        # Count rank (1-based)
        rank = 1
        while w & 1 == 0 and rank <= (64 - self.p):
            rank += 1
            w >>= 1

        # Update register if new rank is larger
        if rank > self._data[j]:
            self._data[j] = rank

    def _add_bloom(self, item_bytes: bytes):
        # Double Hashing Strategy for Bloom
        # h1 (lower 64), h2 (upper 64) from MD5
        h = hashlib.md5(item_bytes).digest()
        h1, h2 = struct.unpack("<QQ", h)

        offset = self.m # Bloom starts after HLL registers

        for i in range(self.bloom_k):
            # Calculate bit index
            bit_idx = (h1 + i * h2) % self.bloom_bits
            byte_idx = offset + (bit_idx // 8)
            mask = 1 << (bit_idx % 8)
            self._data[byte_idx] |= mask

    def __contains__(self, item_bytes: bytes) -> bool:
        """Checks membership using the Bloom Filter component."""
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
        """Returns estimated cardinality using the HyperLogLog component."""
        # Harmonic mean of 2^-M[j]
        # We iterate over the first m bytes of _data

        # Optimization: Count zeros for Linear Counting check
        zeros = 0
        sum_inv = 0.0

        for i in range(self.m):
            val = self._data[i]
            if val == 0:
                zeros += 1
            sum_inv += 2.0 ** (-val)

        E = self.alpha * (self.m ** 2) / sum_inv

        # Small range correction (Linear Counting)
        if E <= 2.5 * self.m:
            if zeros > 0:
                E = self.m * math.log(self.m / zeros)

        # Large range correction (for 64-bit hashes, rarely needed for standard use)
        # (Omitted for simplicity as BeaverDB focuses on embedded scale)

        return int(E)

    def to_bytes(self) -> bytes:
        return bytes(self._data)


class SketchBatch[T: BaseModel]:
    """Context manager for batched updates to an ApproximateSet."""

    def __init__(self, manager: "SketchManager[T]"):
        self._manager = manager
        self._pending_items: list[Any] = []

    def add(self, item: Any):
        self._pending_items.append(item)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if not self._pending_items:
            return

        # Atomic Bulk Update
        with self._manager._internal_lock:
            with self._manager.connection:
                # 1. Reload latest state from DB (critical for consistency)
                self._manager._reload()

                # 2. Update in-memory
                for item in self._pending_items:
                    serialized_item = self._manager._serialize(item)
                    item_bytes = serialized_item.encode("utf-8")
                    self._manager._sketch.add(item_bytes)

                # 3. Save back to DB
                self._manager._save()

        self._pending_items.clear()


class SketchManager[T: BaseModel](ManagerBase[T]):
    """
    Manages a persistent ApproximateSet (Bloom + HLL).
    """

    def __init__(
        self,
        name: str,
        db: IDatabase,
        capacity: int = 1_000_000,
        error_rate: float = 0.01,
        model: type[T] | None = None,
    ):
        # We pass model=None because we handle serialization manually (as bytes)
        super().__init__(name, db, model=model)

        self._capacity = capacity
        self._error_rate = error_rate

        # Initialize or Load
        self._ensure_sketch()

    def _ensure_sketch(self):
        """Loads the sketch from DB or creates it if it doesn't exist."""
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT capacity, error_rate, data FROM beaver_sketches WHERE name = ?",
            (self._name,),
        )
        row = cursor.fetchone()

        if row:
            # Validation: Ensure loaded params match requested params
            db_cap, db_err, db_data = row["capacity"], row["error_rate"], row["data"]

            # Allow small float tolerance
            if db_cap != self._capacity or abs(db_err - self._error_rate) > 1e-9:
                raise ValueError(
                    f"Sketch '{self._name}' exists with capacity={db_cap}, error={db_err}. "
                    f"Cannot load with requested capacity={self._capacity}, error={self._error_rate}."
                )

            self._sketch = ApproximateSet(self._capacity, self._error_rate, data=db_data)
        else:
            # Create new
            self._sketch = ApproximateSet(self._capacity, self._error_rate)
            self._save()

    def _reload(self):
        """Reloads the binary data from the database to refresh state."""
        cursor = self.connection.cursor()
        cursor.execute("SELECT data FROM beaver_sketches WHERE name = ?", (self._name,))
        row = cursor.fetchone()

        if row:
            # We re-initialize the internal bytearray
            self._sketch._data = bytearray(row["data"])

    def _save(self):
        """Persists the current in-memory sketch to the database."""
        self.connection.execute(
            """
            INSERT OR REPLACE INTO beaver_sketches (name, type, capacity, error_rate, data)
            VALUES (?, 'approx_set', ?, ?, ?)
            """,
            (self._name, self._capacity, self._error_rate, self._sketch.to_bytes()),
        )

    @synced
    def add(self, item: T):
        """
        Adds a single item to the sketch.
        WARNING: Slow! Fetches, updates, and saves the full BLOB.
        Use .batched() for bulk operations.
        """
        serialized_item = self._serialize(item)
        item_bytes = serialized_item.encode("utf-8")

        self._reload()
        self._sketch.add(item_bytes)
        self._save()

    def __contains__(self, item: T) -> bool:
        """Checks membership (probabilistic), handling serialization for consistency."""
        serialized_item = self._serialize(item)
        item_bytes = serialized_item.encode("utf-8")

        return item_bytes in self._sketch

    def __len__(self) -> int:
        """Returns approximate cardinality. Uses local cached state."""
        return len(self._sketch)

    def batched(self) -> SketchBatch:
        """Returns a context manager for high-performance bulk updates."""
        return SketchBatch(self)
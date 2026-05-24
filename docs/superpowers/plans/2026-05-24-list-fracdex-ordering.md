# List Fractional-Index Ordering — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace float-midpoint ordering in `AsyncBeaverList` with fractional-index strings to eliminate the crash on contended `insert()` (bug-hunt 2026-05-24).

**Architecture:** Add a pure-Python module `beaver/_fracdex.py` implementing `key_between(a, b)` over a base-62 lexicographic alphabet. Change `__beaver_lists__.item_order REAL → TEXT`. Collapse `push`/`prepend`/`insert` into a single primitive. Gate rc3 databases with `PRAGMA user_version` and a new `BeaverIncompatibleSchemaError`. Bump version to `2.0rc4`.

**Tech Stack:** Python ≥3.12, aiosqlite, pytest + pytest-asyncio. No new runtime dependencies. SQLite-native `PRAGMA user_version` for version tracking.

**Spec:** `docs/superpowers/specs/2026-05-24-list-fracdex-ordering-design.md`

**Working directory:** All paths are relative to the `beaver/` repo root (`/home/apiad/Workspace/repos/beaver/` on this machine). Run all commands from there.

---

## File Structure

Files this plan creates or modifies, with their single responsibility:

- **Create** `beaver/_fracdex.py` — pure ordering primitive. Stateless. ~100 lines. Stdlib only. Single public function `key_between`.
- **Create** `tests/unit/test_fracdex.py` — unit tests for the ordering primitive (invariants, fuzz). Pure, no DB.
- **Modify** `beaver/core.py` — add `BeaverIncompatibleSchemaError`, `BEAVER_DB_VERSION`, `_check_version()`; change `__beaver_lists__` schema from `REAL` to `TEXT`; uncomment the call site at line 175.
- **Modify** `beaver/lists.py` — replace `push` / `prepend` / `insert` ordering logic with `key_between`; remove `_get_order_at_index` and replace with `_get_key_at_index` (returns `str`).
- **Modify** `beaver/__init__.py` — export `BeaverIncompatibleSchemaError`; bump `__version__` to `"2.0rc4"`.
- **Modify** `pyproject.toml` — bump `version` to `"2.0rc4"`.
- **Create** `tests/unit/test_lists_fracdex.py` — regression test for the original bug (1000 inserts at index 1) + fuzz harness vs an in-memory Python list oracle.
- **Create** `tests/unit/test_db_version.py` — version-gate unit tests (fresh DB, rc3-with-data, rc3-empty, newer-than-known).
- **Create** `docs/migration-rc3-to-rc4-lists.md` — user-facing migration recipe.
- **Create** `CHANGELOG.md` — initial CHANGELOG with rc4 entry. Does not exist today.

---

## Task 1: Implement the fracdex ordering primitive (TDD)

**Files:**
- Create: `tests/unit/test_fracdex.py`
- Create: `beaver/_fracdex.py`

### Step 1.1: Write the failing invariant tests

- [ ] Create `tests/unit/test_fracdex.py`:

```python
"""Unit tests for the fracdex ordering primitive.

The primitive is pure (no I/O, no async). Tests verify the core invariants
that the list-ordering layer relies on:

1. key_between(a, b) returns a key strictly between a and b in lex order.
2. None as either bound means "no bound on that side".
3. Output uses only characters from the base-62 alphabet 0-9A-Za-z.
4. Repeated insertion at a contended position grows keys at most logarithmically.
"""

import random
import string

import pytest

from beaver._fracdex import BASE_62_DIGITS, key_between


def test_alphabet_is_lex_sorted():
    # Sanity: the alphabet must be in ASCII-lexicographic order so SQLite TEXT
    # ordering matches our semantic ordering.
    assert list(BASE_62_DIGITS) == sorted(BASE_62_DIGITS)
    assert len(BASE_62_DIGITS) == 62
    assert set(BASE_62_DIGITS) == set(string.digits + string.ascii_uppercase + string.ascii_lowercase)


def test_first_key_is_midpoint_of_space():
    # Empty list initialization: both bounds are None.
    k = key_between(None, None)
    assert isinstance(k, str)
    assert len(k) == 1
    # Must leave room for prepends (key > '0') and appends (key < 'z').
    assert k > "0"
    assert k < "z"


def test_key_strictly_between_two_keys():
    k = key_between("F", "V")
    assert "F" < k < "V"


def test_key_after_simple():
    k = key_between("V", None)
    assert k > "V"


def test_key_before_simple():
    k = key_between(None, "V")
    assert k < "V"


def test_key_between_adjacent_chars_extends():
    # 'F' and 'G' are adjacent in the alphabet; the only way to fit a key
    # between them is to extend.
    k = key_between("F", "G")
    assert "F" < k < "G"
    assert len(k) > 1


def test_key_between_common_prefix():
    k = key_between("FF", "FV")
    assert "FF" < k < "FV"


def test_uses_only_alphabet_chars():
    keys = [key_between(None, None)]
    for _ in range(50):
        keys.append(key_between(keys[-1], None))
    for k in keys:
        assert set(k) <= set(BASE_62_DIGITS)


def test_rejects_a_greater_or_equal_to_b():
    with pytest.raises(ValueError):
        key_between("V", "F")
    with pytest.raises(ValueError):
        key_between("V", "V")


def test_contended_insert_grows_logarithmically():
    # Reproduces the shape of the original bug: insert repeatedly at the
    # same position. Float ordering crashed after 52 calls. Fracdex must
    # tolerate 1000+ and keep keys short.
    low = key_between(None, None)        # 'V' or similar
    high = key_between(low, None)        # > low
    for _ in range(1000):
        mid = key_between(low, high)
        assert low < mid < high
        high = mid                        # next insert squeezes again
    # log_62(1000) ≈ 1.67 → keys of length ~3 are expected; allow slack.
    assert len(high) <= 8, f"key grew too long: {high!r} (len={len(high)})"


def test_random_fuzz_preserves_strict_ordering():
    rng = random.Random(0xBEEF)
    keys = sorted([key_between(None, None)])
    for _ in range(500):
        # Pick a random gap (or boundary) to insert into.
        i = rng.randint(0, len(keys))
        left = keys[i - 1] if i > 0 else None
        right = keys[i] if i < len(keys) else None
        new = key_between(left, right)
        if left is not None:
            assert left < new
        if right is not None:
            assert new < right
        keys.insert(i, new)
    # Final state must still be strictly increasing.
    assert keys == sorted(keys)
    assert len(set(keys)) == len(keys)
```

- [ ] Run tests to verify they fail:

```bash
uv run pytest tests/unit/test_fracdex.py -v
```

Expected: `ImportError: cannot import name 'BASE_62_DIGITS' from 'beaver._fracdex'` (module does not exist yet).

### Step 1.2: Implement the primitive

- [ ] Create `beaver/_fracdex.py`:

```python
"""Fractional-index string ordering for AsyncBeaverList.

Pure Python, standard library only. No I/O, no async.

Keys are non-empty strings over a base-62 alphabet whose ASCII ordering
matches its semantic ordering. ``key_between(a, b)`` returns a key strictly
between ``a`` and ``b`` in lexicographic order (with ``None`` meaning
"unbounded on that side"). Repeated insertion at a contended position grows
keys logarithmically rather than collapsing — which is the failure mode of
the previous float-midpoint scheme.

Invariant: produced keys never end in the minimum digit ('0'). This keeps
``_midpoint`` terminating and the inductive growth argument clean.
"""

BASE_62_DIGITS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def key_between(a: str | None, b: str | None) -> str:
    """Return a key ``k`` such that ``a < k < b`` in lex order.

    ``a=None`` means "no lower bound" (used by ``prepend``).
    ``b=None`` means "no upper bound" (used by ``push``).
    Both ``None`` returns the midpoint of the key space (used to seed an
    empty list).
    """
    a_s = a if a is not None else ""
    if b is not None and a_s >= b:
        raise ValueError(f"a must be strictly less than b: a={a!r} b={b!r}")
    return _midpoint(a_s, b)


def _midpoint(a: str, b: str | None) -> str:
    # Length of longest common prefix between a and b (treating b=None as
    # unbounded — no common prefix).
    n = 0
    while n < len(a) and b is not None and n < len(b) and a[n] == b[n]:
        n += 1
    if n > 0:
        return a[:n] + _midpoint(a[n:], b[n:] if b is not None else None)

    # No common prefix. Look at the first differing digit on each side.
    digit_a = BASE_62_DIGITS.index(a[0]) if a else 0
    digit_b = (
        BASE_62_DIGITS.index(b[0]) if (b is not None and len(b) > 0) else len(BASE_62_DIGITS)
    )

    if digit_b - digit_a > 1:
        # Room for a midpoint digit at this position.
        mid = (digit_a + digit_b) // 2
        return BASE_62_DIGITS[mid]

    # Digits are adjacent (or b shares a's leading digit with extra suffix).
    # Need to extend.
    if b is not None and len(b) > 1:
        # Use b's leading digit and recurse on (empty, rest of b) to land
        # below the rest of b at the next position.
        return b[:1] + _midpoint("", b[1:])

    # b is None or single-digit. Use a's leading digit (or '0' if a empty)
    # and extend after a.
    a_first = a[:1] if a else BASE_62_DIGITS[0]
    return a_first + _midpoint(a[1:] if len(a) > 1 else "", None)
```

- [ ] Run tests to verify they pass:

```bash
uv run pytest tests/unit/test_fracdex.py -v
```

Expected: 10/10 PASS.

### Step 1.3: Commit

- [ ] Stage and commit:

```bash
git add beaver/_fracdex.py tests/unit/test_fracdex.py
git commit -m "feat(fracdex): add lex-ordered fractional-index primitive

Pure Python, no new deps. ~50 lines + tests. Repeated insertion at a
contended position grows keys logarithmically instead of collapsing —
the failure mode that crashes list.insert() under the float-midpoint
scheme.

Refs: docs/superpowers/specs/2026-05-24-list-fracdex-ordering-design.md"
```

---

## Task 2: Add DB version gate

**Files:**
- Modify: `beaver/core.py:175` (uncomment `await self._check_version()`)
- Modify: `beaver/core.py` (add class `BeaverIncompatibleSchemaError`, constant `BEAVER_DB_VERSION`, method `_check_version`, and update `__beaver_lists__` schema)
- Modify: `beaver/__init__.py` (export `BeaverIncompatibleSchemaError`)
- Create: `tests/unit/test_db_version.py`

### Step 2.1: Read the current state of core.py

- [ ] Read these regions of `beaver/core.py`:
  - Top of file (imports + module-level constants).
  - `connect()` method — note the commented `# await self._check_version()` line near the end.
  - `_create_all_tables()` — locate the `__beaver_lists__` CREATE TABLE statement (column type `REAL` to be changed).

The exact line numbers will have drifted slightly since the spec was written; use the symbol names as anchors, not the numbers.

### Step 2.2: Write failing tests

- [ ] Create `tests/unit/test_db_version.py`:

```python
"""Tests for the DB version gate added in rc4.

rc4 uses SQLite's PRAGMA user_version to detect databases written by older
beaver versions (which used REAL item_order in __beaver_lists__). Opening
such a database against rc4 must raise BeaverIncompatibleSchemaError unless
the list table is empty (in which case we silently upgrade).
"""

import sqlite3
import uuid

import pytest

from beaver import AsyncBeaverDB, BeaverIncompatibleSchemaError
from beaver.core import BEAVER_DB_VERSION

pytestmark = pytest.mark.asyncio


def _make_rc3_db_with_list(path: str, with_row: bool) -> None:
    """Write a database that looks like one created by rc3 (no user_version
    set, REAL item_order column)."""
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE __beaver_lists__ (
            list_name TEXT NOT NULL,
            item_order REAL NOT NULL,
            item_value TEXT NOT NULL,
            PRIMARY KEY (list_name, item_order)
        )
        """
    )
    if with_row:
        conn.execute(
            "INSERT INTO __beaver_lists__ (list_name, item_order, item_value) VALUES (?, ?, ?)",
            ("seed", 1.0, '"hello"'),
        )
    conn.commit()
    conn.close()


@pytest.fixture
def tmp_db(tmp_path):
    return str(tmp_path / f"{uuid.uuid4().hex}.db")


async def test_fresh_db_sets_user_version(tmp_db):
    db = AsyncBeaverDB(tmp_db)
    await db.connect()
    try:
        cursor = await db._connection.execute("PRAGMA user_version")
        (v,) = await cursor.fetchone()
        assert v == BEAVER_DB_VERSION
    finally:
        await db.close()


async def test_rc3_db_with_lists_data_raises(tmp_db):
    _make_rc3_db_with_list(tmp_db, with_row=True)
    db = AsyncBeaverDB(tmp_db)
    with pytest.raises(BeaverIncompatibleSchemaError):
        await db.connect()


async def test_rc3_db_with_empty_lists_upgrades(tmp_db):
    _make_rc3_db_with_list(tmp_db, with_row=False)
    db = AsyncBeaverDB(tmp_db)
    await db.connect()
    try:
        # user_version is now the current version.
        cursor = await db._connection.execute("PRAGMA user_version")
        (v,) = await cursor.fetchone()
        assert v == BEAVER_DB_VERSION
        # Column type was upgraded to TEXT.
        cursor = await db._connection.execute(
            "SELECT type FROM pragma_table_info('__beaver_lists__') WHERE name = 'item_order'"
        )
        (col_type,) = await cursor.fetchone()
        assert col_type == "TEXT"
    finally:
        await db.close()


async def test_newer_db_raises(tmp_db):
    conn = sqlite3.connect(tmp_db)
    conn.execute(f"PRAGMA user_version = {BEAVER_DB_VERSION + 99}")
    conn.commit()
    conn.close()
    db = AsyncBeaverDB(tmp_db)
    with pytest.raises(BeaverIncompatibleSchemaError):
        await db.connect()
```

- [ ] Run tests to verify they fail:

```bash
uv run pytest tests/unit/test_db_version.py -v
```

Expected: `ImportError` for `BeaverIncompatibleSchemaError` and/or `BEAVER_DB_VERSION` (don't exist yet).

### Step 2.3: Add the exception class and constant

- [ ] In `beaver/core.py`, near the top of the file (after the imports, before any class definitions), add:

```python
BEAVER_DB_VERSION = 1


class BeaverIncompatibleSchemaError(RuntimeError):
    """Raised when opening a database whose schema is incompatible with this
    version of beaver. The user must dump-and-reload to migrate.
    See docs/migration-rc3-to-rc4-lists.md."""
```

### Step 2.4: Change the lists table schema to TEXT

- [ ] In `beaver/core.py`, locate the `CREATE TABLE IF NOT EXISTS __beaver_lists__` statement in `_create_all_tables()` (currently around line 258-265) and change `item_order REAL NOT NULL` to `item_order TEXT NOT NULL`. The PRIMARY KEY clause stays the same.

After change:

```python
await c.execute(
    """
    CREATE TABLE IF NOT EXISTS __beaver_lists__ (
        list_name TEXT NOT NULL,
        item_order TEXT NOT NULL,
        item_value TEXT NOT NULL,
        PRIMARY KEY (list_name, item_order)
    )
"""
)
```

### Step 2.5: Implement `_check_version`

- [ ] In `beaver/core.py`, add a method on the same class that owns `connect()` / `_create_all_tables()` (it's `AsyncBeaverDB`):

```python
async def _check_version(self) -> None:
    """Verify the open database is compatible with this beaver version.

    On a brand-new database the user_version is 0; we accept that and stamp
    it to BEAVER_DB_VERSION after _create_all_tables has run. On a rc3-era
    database (user_version 0, __beaver_lists__ exists with REAL item_order),
    we raise unless the lists table is empty (in which case we drop and
    let _create_all_tables recreate it with the new schema).
    """
    cursor = await self._connection.execute("PRAGMA user_version")
    row = await cursor.fetchone()
    current = row[0] if row else 0

    if current == BEAVER_DB_VERSION:
        return

    if current > BEAVER_DB_VERSION:
        raise BeaverIncompatibleSchemaError(
            f"Database user_version is {current}; this beaver only understands "
            f"up to {BEAVER_DB_VERSION}. The database was written by a newer "
            "beaver release."
        )

    # current < BEAVER_DB_VERSION → upgrade path (currently only 0 → 1).
    # Check whether __beaver_lists__ exists with the old REAL column.
    cursor = await self._connection.execute(
        "SELECT type FROM pragma_table_info('__beaver_lists__') WHERE name = 'item_order'"
    )
    row = await cursor.fetchone()
    if row is not None and row[0].upper() == "REAL":
        cursor = await self._connection.execute(
            "SELECT 1 FROM __beaver_lists__ LIMIT 1"
        )
        has_row = await cursor.fetchone()
        if has_row is not None:
            raise BeaverIncompatibleSchemaError(
                "This database was created by beaver < 2.0rc4 and contains "
                "persistent-list data using the old REAL ordering format. "
                "rc4 changed __beaver_lists__.item_order from REAL to TEXT "
                "(fractional indexing) and no automatic migration is "
                "provided. See docs/migration-rc3-to-rc4-lists.md."
            )
        # Empty old-format table: drop it so _create_all_tables can rebuild
        # it with the new TEXT column.
        await self._connection.execute("DROP TABLE __beaver_lists__")
```

### Step 2.6: Wire `_check_version` into `connect()`

- [ ] In `beaver/core.py`, find the commented line in `connect()`:

```python
await self._create_all_tables()
# await self._check_version()
```

Replace those two lines with the correct ordering — check first, then create tables (so the drop happens before CREATE IF NOT EXISTS), then stamp the version:

```python
await self._check_version()
await self._create_all_tables()
await self._connection.execute(f"PRAGMA user_version = {BEAVER_DB_VERSION}")
```

### Step 2.7: Export the exception

- [ ] Edit `beaver/__init__.py` — add `BeaverIncompatibleSchemaError` to the imports and `__all__`:

```python
from .core import BeaverDB, AsyncBeaverDB, BeaverIncompatibleSchemaError
from .docs import Document
from .events import Event
from .queries import q
from .security import Secret

__version__ = "2.0rc4"

__all__ = [
    "AsyncBeaverDB",
    "BeaverDB",
    "BeaverIncompatibleSchemaError",
    "Document",
    "Secret",
    "Event",
    "q",
]
```

### Step 2.8: Run the version tests

- [ ] Run:

```bash
uv run pytest tests/unit/test_db_version.py -v
```

Expected: 4/4 PASS.

### Step 2.9: Commit

- [ ] Stage and commit:

```bash
git add beaver/core.py beaver/__init__.py tests/unit/test_db_version.py
git commit -m "feat(core): gate rc3 databases with PRAGMA user_version

Adds BEAVER_DB_VERSION=1, BeaverIncompatibleSchemaError, and _check_version()
called from connect(). Fresh DBs are stamped. rc3 DBs with persistent-list
data are rejected with an actionable message pointing to the migration doc.
rc3 DBs with empty lists are silently upgraded by dropping the old REAL-typed
table before _create_all_tables() rebuilds it as TEXT."
```

---

## Task 3: Migrate `AsyncBeaverList` to fracdex

**Files:**
- Modify: `beaver/lists.py` (rewrite `push`, `prepend`, `insert`; replace `_get_order_at_index` with `_get_key_at_index`)

### Step 3.1: Read the current state

- [ ] Read `beaver/lists.py` lines covering `_get_order_at_index`, `push`, `prepend`, and `insert` (currently around lines 190-258). Note the `@emits` / `@atomic` decorator order — preserve it exactly.

### Step 3.2: Replace `_get_order_at_index` with `_get_key_at_index`

- [ ] In `beaver/lists.py`, locate:

```python
async def _get_order_at_index(self, index: int) -> float:
    """Helper to get the float item_order at a specific index."""
    cursor = await self.connection.execute(
        "SELECT item_order FROM __beaver_lists__ WHERE list_name = ? ORDER BY item_order ASC LIMIT 1 OFFSET ?",
        (self._name, index),
    )
    result = await cursor.fetchone()

    if result:
        return result[0]
    raise IndexError(f"{index} out of range.")
```

Replace with:

```python
async def _get_key_at_index(self, index: int) -> str:
    """Helper to get the item_order string key at a specific index."""
    cursor = await self.connection.execute(
        "SELECT item_order FROM __beaver_lists__ WHERE list_name = ? ORDER BY item_order ASC LIMIT 1 OFFSET ?",
        (self._name, index),
    )
    result = await cursor.fetchone()

    if result:
        return result[0]
    raise IndexError(f"{index} out of range.")
```

Then search-and-replace remaining call sites: `_get_order_at_index` is called only inside `insert()` (twice). Update both call sites in `insert()` per Step 3.5 below.

### Step 3.3: Add the fracdex import

- [ ] At the top of `beaver/lists.py`, add (alongside existing imports):

```python
from ._fracdex import key_between
```

### Step 3.4: Rewrite `push` and `prepend`

- [ ] Replace the current `push` method body with:

```python
@emits("push", payload=lambda *args, **kwargs: dict())
@atomic
async def push(self, value: T):
    """Pushes an item to the end of the list."""
    cursor = await self.connection.execute(
        "SELECT MAX(item_order) FROM __beaver_lists__ WHERE list_name = ?",
        (self._name,),
    )
    row = await cursor.fetchone()
    max_key = row[0] if row and row[0] is not None else None
    new_key = key_between(max_key, None)

    await self.connection.execute(
        "INSERT INTO __beaver_lists__ (list_name, item_order, item_value) VALUES (?, ?, ?)",
        (self._name, new_key, self._serialize(value)),
    )
```

- [ ] Replace the current `prepend` method body with:

```python
@emits("prepend", payload=lambda *args, **kwargs: dict())
@atomic
async def prepend(self, value: T):
    """Prepends an item to the beginning of the list."""
    cursor = await self.connection.execute(
        "SELECT MIN(item_order) FROM __beaver_lists__ WHERE list_name = ?",
        (self._name,),
    )
    row = await cursor.fetchone()
    min_key = row[0] if row and row[0] is not None else None
    new_key = key_between(None, min_key)

    await self.connection.execute(
        "INSERT INTO __beaver_lists__ (list_name, item_order, item_value) VALUES (?, ?, ?)",
        (self._name, new_key, self._serialize(value)),
    )
```

### Step 3.5: Rewrite `insert`

- [ ] Replace the current `insert` method body with:

```python
@emits("insert", payload=lambda index, *args, **kwargs: dict(index=index))
@atomic
async def insert(self, index: int, value: T):
    """Inserts an item at a specific index using fractional-index ordering."""
    list_len = await self.count()

    if index <= 0:
        await self.prepend(value)
        return
    if index >= list_len:
        await self.push(value)
        return

    left_key = await self._get_key_at_index(index - 1)
    right_key = await self._get_key_at_index(index)
    new_key = key_between(left_key, right_key)

    await self.connection.execute(
        "INSERT INTO __beaver_lists__ (list_name, item_order, item_value) VALUES (?, ?, ?)",
        (self._name, new_key, self._serialize(value)),
    )
```

### Step 3.6: Run the existing list test suite

- [ ] Run:

```bash
uv run pytest tests/unit/test_lists.py -v
```

Expected: All previously-passing tests continue to pass. (The existing tests exercise `push`, `prepend`, `pop`, `deque`, `get`, `set`, `delete`, `slice`, `__aiter__` — none of which depend on the underlying type of `item_order`. They should be entirely unaffected.)

If any tests fail, do not proceed. Debug, fix, then re-run before continuing.

### Step 3.7: Commit

- [ ] Stage and commit:

```bash
git add beaver/lists.py
git commit -m "feat(lists): use fracdex strings for item_order

Replaces the float-midpoint scheme in push/prepend/insert with a single
ordering primitive key_between(left, right). __beaver_lists__.item_order
is now TEXT (already changed in the schema CREATE statement).

This eliminates the IntegrityError crash at contended insert() positions
(bug-hunt 2026-05-24). Existing list tests pass unchanged."
```

---

## Task 4: Regression test for the original bug

**Files:**
- Create: `tests/unit/test_lists_fracdex.py`

### Step 4.1: Write the regression test

- [ ] Create `tests/unit/test_lists_fracdex.py`:

```python
"""Integration tests for the fracdex-based list ordering.

These tests exercise AsyncBeaverList through the public API to confirm
the bug-hunt finding from 2026-05-24 is fixed and that the new ordering
behaves correctly under random workloads.
"""

import random

import pytest

from beaver import AsyncBeaverDB

pytestmark = pytest.mark.asyncio


async def test_insert_at_contended_index_does_not_crash(async_db_mem: AsyncBeaverDB):
    """The original bug: insert(1, ...) crashed at ~52 calls under the
    float-midpoint scheme. With fracdex it must survive 1000+."""
    lst = async_db_mem.list("contended")
    await lst.push("first")
    await lst.push("last")
    # 1000 inserts at the same contended index. Pre-fix this crashed at ~52.
    for i in range(1000):
        await lst.insert(1, f"v{i}")
    assert await lst.count() == 1002
    # First and last items unchanged; the 1000 inserts sit between them.
    assert await lst.get(0) == "first"
    assert await lst.get(-1) == "last"


async def test_insert_preserves_strict_ordering(async_db_mem: AsyncBeaverDB):
    """After many inserts, iterating the list returns items in the order
    they would be in if the list were maintained in-memory."""
    lst = async_db_mem.list("ordering")
    await lst.push("a")
    await lst.push("z")
    # Insert items at index 1 in order; expected list: ['a', '99', '98', ..., '00', 'z']
    for i in range(100):
        await lst.insert(1, f"{i:02d}")
    expected = ["a"] + [f"{i:02d}" for i in reversed(range(100))] + ["z"]
    actual = [item async for item in lst]
    assert actual == expected
```

### Step 4.2: Run the regression test

- [ ] Run:

```bash
uv run pytest tests/unit/test_lists_fracdex.py -v
```

Expected: 2/2 PASS.

### Step 4.3: Commit

- [ ] Stage and commit:

```bash
git add tests/unit/test_lists_fracdex.py
git commit -m "test(lists): regression test for contended insert collapse

Reproduces the 2026-05-24 bug-hunt finding. Pre-fix: crashed at insertion
#52 with sqlite3.IntegrityError. Post-fix: 1000 inserts at index 1 succeed
and the resulting list is correctly ordered."
```

---

## Task 5: Fuzz test against an in-memory oracle

**Files:**
- Modify: `tests/unit/test_lists_fracdex.py` (append a new test)

### Step 5.1: Write the fuzz test

- [ ] Append to `tests/unit/test_lists_fracdex.py`:

```python
async def test_fuzz_against_python_list_oracle(async_db_mem: AsyncBeaverDB):
    """Random sequence of push/prepend/insert/pop/deque/get operations.
    The in-memory Python list is the oracle; the persisted list must match
    after every operation."""
    rng = random.Random(0xC0DE)
    lst = async_db_mem.list("fuzz")
    oracle: list[str] = []

    ops = ["push", "prepend", "insert", "pop", "deque"]
    for step in range(1000):
        op = rng.choice(ops)
        if op == "push":
            v = f"v{step}"
            await lst.push(v)
            oracle.append(v)
        elif op == "prepend":
            v = f"v{step}"
            await lst.prepend(v)
            oracle.insert(0, v)
        elif op == "insert":
            if len(oracle) == 0:
                continue
            i = rng.randint(0, len(oracle))
            v = f"v{step}"
            await lst.insert(i, v)
            oracle.insert(i, v)
        elif op == "pop":
            persisted = await lst.pop()
            expected = oracle.pop() if oracle else None
            assert persisted == expected, f"step {step} op {op}"
        elif op == "deque":
            persisted = await lst.deque()
            expected = oracle.pop(0) if oracle else None
            assert persisted == expected, f"step {step} op {op}"

        # Every 50 ops, snapshot the full list and compare.
        if step % 50 == 0:
            actual = [item async for item in lst]
            assert actual == oracle, f"divergence at step {step}: {actual} != {oracle}"

    # Final state must match exactly.
    actual = [item async for item in lst]
    assert actual == oracle
    assert await lst.count() == len(oracle)
```

### Step 5.2: Run the fuzz test

- [ ] Run:

```bash
uv run pytest tests/unit/test_lists_fracdex.py::test_fuzz_against_python_list_oracle -v
```

Expected: PASS. Runtime ~5-15 seconds.

If divergence is reported, the assertion message points at the step and operation. Do not weaken the test — debug the underlying ordering bug.

### Step 5.3: Run the full suite

- [ ] Run the complete unit-test suite to confirm no regressions:

```bash
uv run pytest tests/unit/ -v
```

Expected: All tests pass.

### Step 5.4: Commit

- [ ] Stage and commit:

```bash
git add tests/unit/test_lists_fracdex.py
git commit -m "test(lists): fuzz fracdex ordering vs Python list oracle

1000-step random sequence of push/prepend/insert/pop/deque. Periodic
full-list snapshot + final-state comparison. Confirms the new ordering
matches list semantics under arbitrary workloads."
```

---

## Task 6: Migration doc, CHANGELOG, version bump

**Files:**
- Create: `docs/migration-rc3-to-rc4-lists.md`
- Create: `CHANGELOG.md`
- Modify: `pyproject.toml` (`version`)
- (`beaver/__init__.py` `__version__` was already bumped in Task 2.7)

### Step 6.1: Write the migration doc

- [ ] Create `docs/migration-rc3-to-rc4-lists.md`:

```markdown
# Migrating persistent lists from rc3 to rc4

`beaver-db 2.0rc4` changes the on-disk format of persistent lists.
`__beaver_lists__.item_order` was a `REAL` (float) column with a midpoint
insertion scheme that crashed after ~52 inserts at the same index. It is
now a `TEXT` (fractional-index string) column that does not collapse.

Databases created by `2.0rc3` or earlier are rejected on open by rc4 with
`BeaverIncompatibleSchemaError`. No automatic migration is provided. To
migrate your data:

## 1. With rc3 still installed, dump each list to JSON

```python
import json
import asyncio
from beaver import AsyncBeaverDB

async def dump(path: str, list_names: list[str], out: str):
    db = AsyncBeaverDB(path)
    await db.connect()
    try:
        result = {}
        for name in list_names:
            lst = db.list(name)
            result[name] = [item async for item in lst]
        with open(out, "w") as f:
            json.dump(result, f, indent=2)
    finally:
        await db.close()

asyncio.run(dump("old.db", ["queue", "todo", "..."], "lists.json"))
```

You must know the names of the lists you created — beaver does not enumerate
them. If you don't have them recorded, query the database directly:

```bash
sqlite3 old.db "SELECT DISTINCT list_name FROM __beaver_lists__"
```

## 2. Upgrade to rc4 and load into a fresh database

```python
import json
import asyncio
from beaver import AsyncBeaverDB

async def load(path: str, src: str):
    db = AsyncBeaverDB(path)
    await db.connect()
    try:
        data = json.load(open(src))
        for name, items in data.items():
            lst = db.list(name)
            for item in items:
                await lst.push(item)
    finally:
        await db.close()

asyncio.run(load("new.db", "lists.json"))
```

If your lists held Pydantic models, hand the model class to `db.list(name, Model)` and
serialize/deserialize accordingly — this script assumes JSON-roundtrippable values.

## 3. Verify, then swap

Sanity-check counts and a few values before retiring `old.db`. The dump
file `lists.json` is your backup until you do.
```

### Step 6.2: Write the CHANGELOG

- [ ] Create `CHANGELOG.md`:

```markdown
# Changelog

All notable changes to beaver-db will be recorded here.

## 2.0rc4 — 2026-05-24

### Breaking

- **Persistent-list storage format changed.** `__beaver_lists__.item_order`
  is now `TEXT` (fractional index) instead of `REAL`. Fixes a hard crash in
  `AsyncBeaverList.insert()` after ~52 inserts at the same contended index
  (bug-hunt 2026-05-24, float-midpoint collapse against the `UNIQUE`
  constraint on `(list_name, item_order)`).
- Databases created by `2.0rc3` or earlier are rejected on open with
  `BeaverIncompatibleSchemaError`. See
  `docs/migration-rc3-to-rc4-lists.md` for the dump-and-reload recipe.

### Added

- `BeaverIncompatibleSchemaError`, exported from `beaver`.
- DB version tracking via SQLite's built-in `PRAGMA user_version`. Current
  version: `1`.
```

### Step 6.3: Bump the package version

- [ ] In `pyproject.toml`, change:

```toml
version = "2.0rc3"
```

to:

```toml
version = "2.0rc4"
```

### Step 6.4: Run the full test suite

- [ ] Final check across all tests:

```bash
uv run pytest -v
```

Expected: All tests pass. No regressions.

### Step 6.5: Commit

- [ ] Stage and commit:

```bash
git add docs/migration-rc3-to-rc4-lists.md CHANGELOG.md pyproject.toml
git commit -m "chore(release): 2.0rc4 — fracdex list ordering

- Bump pyproject version to 2.0rc4 (__init__.py already at rc4).
- Add CHANGELOG.md with the breaking-change entry.
- Add docs/migration-rc3-to-rc4-lists.md with dump-and-reload recipe."
```

---

## Self-review checklist (for the implementer)

After completing all tasks, sanity-check:

- [ ] `uv run pytest -v` — all tests pass.
- [ ] `grep -rn "_get_order_at_index" beaver/ tests/` returns nothing — the old helper was fully removed.
- [ ] `grep -rn "REAL" beaver/core.py` — no `REAL` left in `__beaver_lists__`.
- [ ] `python -c "from beaver import BeaverIncompatibleSchemaError; print(BeaverIncompatibleSchemaError.__mro__)"` — exception is exported and inherits from `RuntimeError`.
- [ ] `git log --oneline | head -10` — six commits in order: fracdex primitive, version gate, lists migration, regression test, fuzz test, release.

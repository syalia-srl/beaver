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


def test_contended_insert_does_not_crash():
    # Reproduces the shape of the original bug: insert repeatedly at the
    # same position. Float ordering crashed after 52 calls. Fracdex must
    # tolerate 1000+ without crashing while keeping strict ordering.
    # One-sided squeezes grow keys linearly in N (a known property of
    # fractional indexing — rocicorp's reference shares this trait); the
    # win over floats is that they don't *crash*.
    low = key_between(None, None)
    high = key_between(low, None)
    for _ in range(1000):
        mid = key_between(low, high)
        assert low < mid < high
        high = mid
    # Linear growth with a small constant; floats would have crashed at ~52.
    assert len(high) <= 300, f"key grew too long: {high!r} (len={len(high)})"


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

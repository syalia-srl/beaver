"""Fractional-index string ordering for AsyncBeaverList.

Pure Python, standard library only. No I/O, no async.

Keys are non-empty strings over a base-62 alphabet whose ASCII ordering
matches its semantic ordering. ``key_between(a, b)`` returns a key strictly
between ``a`` and ``b`` in lexicographic order (with ``None`` meaning
"unbounded on that side"). Repeated insertion at a contended position grows
keys logarithmically rather than collapsing — which is the failure mode of
the previous float-midpoint scheme.
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
        BASE_62_DIGITS.index(b[0])
        if (b is not None and len(b) > 0)
        else len(BASE_62_DIGITS)
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

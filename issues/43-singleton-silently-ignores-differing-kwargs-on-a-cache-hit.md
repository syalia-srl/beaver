---
number: 43
title: "singleton() silently ignores differing kwargs on a cache hit, so a later declaration vanishes"
state: open
labels:
- bug
- api
---

### 1. Summary

`AsyncBeaverDB.singleton()` keys its manager cache on `(cls, name)` alone and
**drops every keyword argument on a cache hit**. Re-opening the same collection
with a *different* `model=`, `secret=` or `indexed=` returns the manager built
by the first call, and the second call's arguments are discarded without a word.

The failure is silent. Nothing raises, nothing warns, and the returned object
looks exactly like the one that was asked for.

### 2. The mechanism

```python
# beaver/core.py:634-646
def singleton[T: AsyncBeaverBase](self, cls: type[T], name, **kwargs) -> T:
    cache_key = (cls, name)          # <- kwargs are not part of the key

    if cache_key not in self._manager_cache:
        instance = cls(name=name, db=self, **kwargs)   # <- only ever used here
        self._manager_cache[cache_key] = instance

    return self._manager_cache[cache_key]
```

On the second call `kwargs` is evaluated, passed in, and then thrown away.

### 3. Why it matters now — field indexing

Issue #42 adds `indexed=` to the `log()` factory. That makes the bug reachable
from a plausible, correct-looking call sequence:

```python
db.log("audit")                          # somewhere early — a read, a helper, a health check
...
db.log("audit", indexed=["actor_id"])    # the real declaration
```

The second call returns the **already-cached, undeclared** manager. `_indexed`
stays empty, so:

- no index rows are ever written for `audit`;
- the manifest never records the field;
- `range(where=...)` still returns *correct* results, because an undeclared
  field falls back to the `json_extract` scan (#42 §3.5).

So the only symptom is that the index the developer asked for does not exist and
never will. `indexes()` reports an empty list, which is at least truthful — but
only if someone thinks to look.

This is the shape issue #41 warns about: the danger is never the error, it is
the silence. A declaration that quietly does nothing is worse than one that
refuses.

It also affects `model=` and `secret=` on the other factories, which have the
same problem today and always have.

### 4. Options

1. **Include the kwargs in the cache key.** Simple, but two managers for the
   same collection with different models is its own kind of confusing, and
   `secret=` would end up in a dict key.
2. **Raise on conflict.** If a cached manager exists and the new kwargs differ
   from the ones it was built with, raise. Loud, and matches "silence is the
   bug" — but turns today's working-by-accident call sequences into errors.
3. **Honour the new kwargs**, applying them to the cached instance. Sounds
   friendly, is the hardest to get right: `indexed=` can be applied late, but
   `model=` and `secret=` cannot be changed under an instance that may already
   hold state.

Option 2 is the closest fit to the house rule, with option 1 as the fallback if
the churn proves unacceptable. Whichever is chosen, the current behaviour —
accept the arguments, ignore them, say nothing — should not survive.

### 5. Workaround until then

Declare on first use. Open a collection with its full argument list the first
time it is touched in a process, and never re-open it with different arguments.
Tests that need to re-open with a declaration must clear the cache:

```python
db._manager_cache.clear()
log = db.log("audit", model=Event, indexed=["actor"])
```

### 6. Testing

- Open a collection bare, re-open it with `indexed=[...]`, and assert the
  chosen behaviour (raise, or a manager whose `_indexed` is populated).
- Same for `model=` and `secret=`.
- Assert the single-call path is unaffected — this must not cost anything for
  the overwhelmingly common case of opening a collection the same way twice.

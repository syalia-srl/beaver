---
number: 44
title: "Filters have no CLI or wire encoding, so explain() and where= cannot cross the SID boundary"
state: open
labels:
- enhancement
- api
- cli
---

### 1. Summary

`q()` builds `Filter` dataclasses (`beaver/queries.py:6` — `path`, `operator`,
`value`), and they are Python objects with **no serialized form**. Any `@expose`d
method that takes filters therefore cannot reach the CLI or the remote client,
because neither can construct a `Filter`.

This surfaced implementing #42 slice 2. `AsyncBeaverLog.explain(where=[...])`
was written `@expose`d, per #42 §3.8, and it breaks CLI construction at import
time:

```
beaver/cli/discovery.py:180: in _build_command
    raise NotImplementedError(f"No CLI shape for {method_name} (path={meta.path})")
E   NotImplementedError: No CLI shape for explain (path=/explain)
```

`explain` is `@local_only` for now, naming this issue. `indexes()` takes no
arguments and is exposed normally.

### 2. Scope — this is bigger than `explain`

The same gap limits `range(where=...)` — but **it fails loudly, and that is worth
being precise about**, because the first draft of this issue claimed otherwise:

- **Remote client.** `RemoteLog.range` (`client.py:268`) has a hand-written
  signature of exactly `start`, `end`, `limit`. Passing `where`, `order` or
  `offset` raises `TypeError`; it does **not** forward them and does **not**
  return an unfiltered result set. Verified by binding the signature:

  ```
  RemoteLog.range params: ['start', 'end', 'limit']
    where:  TypeError    order: TypeError    offset: TypeError
  ```

  So this is a **missing feature**, not a silent-wrong-answer bug. An earlier
  version of this issue said a filtered `range()` "degrades to unfiltered over
  the wire" — that was wrong, and overstating a bug is its own cost: it sends
  whoever picks this up hunting for a data-integrity failure that does not exist.
- **CLI.** `_build_command`'s `range` shape (`discovery.py:131`) passes only
  `start`, `end` and `limit`, so `beaver log range` cannot filter. A user asking
  for a filter they cannot express gets no option to pass, rather than a wrong
  answer.

The **server** side is the one place still worth checking when this is fixed: a
hand-crafted `GET /logs/<name>/range?where=…` bypasses the client's signature, so
whatever encoding lands must reject unknown or malformed filter params rather
than ignore them.

And it will recur for every collection in #42 slices 3–6, plus `aggregate()`
in slice 4, all of which take `where=`.

`docs().where()` has always had this limitation, so nothing regressed — but the
uniformity #42 promises makes it much more visible.

### 3. What is needed

A JSON encoding for a filter list, used by both the CLI and the REST body:

```json
[{"path": "actor_id", "operator": "==", "value": "alex"},
 {"path": "duration_ms", "operator": ">", "value": 1000}]
```

Then:

1. `Filter` gains a round-trip (`to_dict` / `from_dict`, or make it a pydantic
   model — it is already a dataclass with three plain fields).
2. `discovery.py` grows a shape for `--where '<json>'`, decoded with the
   existing `_read_json_value`, and `range`'s shape gains the same option.
3. The server decodes the same structure from the request body.
4. `explain` goes back to `@expose`, as #42 §3.8 intends.

**The operator must be validated against an allowlist on the way in.** It is
interpolated straight into SQL (`indexing.py`, `compile_scan_filters` and
`compile_indexed_filter`), which is safe today only because `Filter.operator`
can currently be produced solely by `Query`'s dunder methods. The moment an
operator can arrive as a string from a CLI argument or an HTTP body, that stops
being true and it becomes an injection vector. Whitelist `==`, `!=`, `>`, `>=`,
`<`, `<=` and reject everything else.

### 4. Testing

- Round-trip a filter list through the encoding and assert the compiled SQL and
  parameters are identical to the ones built by `q()` directly.
- `beaver log <name> range --where '<json>'` returns the same rows as the
  equivalent in-process call.
- A filter arriving with an operator outside the allowlist is rejected, and the
  rejection is asserted against the *substrate* — no query is executed.
- `explain` reaches the CLI and the remote client once re-exposed.

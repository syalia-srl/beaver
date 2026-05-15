---
number: 28
title: "Vector strategy beyond Linear/LSH (numpy-only HNSW or alternative)"
state: open
labels:
  - deferred
---

> **Status: deferred indefinitely (2026-05-15).** Originally scoped as a
> `hnswlib`-backed strategy with a `[hnsw]` extra. We are dropping that
> approach: beaver's dependency floor is **numpy-only** for vector indexing.
> No `hnswlib`, no `faiss`, no compiled C++ wheels.
>
> The issue stays open as a placeholder. It unfreezes only if/when we
> design a pure-numpy implementation (HNSW, IVF-PQ, ScaNN-style, or
> something else) that beats the current Linear / LSH strategies on the
> >100k-vector regime without adding heavy dependencies. Until then,
> Linear is the workhorse and LSH (#24) is the optional approximate path.
>
> **Removed from the v2.0 release scope** — see Phase 1 tracker (#38).

## Why deferred

- Compiled-wheel dependencies (`hnswlib`, `faiss`) are a recurring
  install-pain source on edge platforms (Apple Silicon, Alpine, Pi,
  WASM-adjacent runtimes). beaver-db's appeal is "single-file SQLite +
  pip install"; adding a compiler-toolchain risk for one optional
  feature undercuts that.
- numpy is already a hard dependency. A numpy-only ANN strategy
  preserves beaver's distribution story.
- LSH (#24) already covers the "approximate, sub-linear" niche for the
  vector volumes most beaver users will see. The HNSW gap matters only
  in the >100k regime, which we don't have a confirmed user for yet.

## What would unfreeze this

A concrete design for a pure-numpy ANN index that:

1. Beats LSH recall on small/uniform datasets (LSH currently underperforms
   on the smoke; see STATUS.md).
2. Hits sub-linear scaling on >100k vectors with reasonable build time.
3. Persists to a single SQLite BLOB so the "single-file" property holds.
4. Adds zero non-numpy dependencies.

Candidates worth sketching when this comes back: navigable small-world
graph in pure numpy, IVF-PQ with numpy quantization, hierarchical k-means.

## Original spec (preserved for reference)

The original `hnswlib`-based design lived here through 2026-05-15. Recover
from git history (`git log --diff-filter=M -- issues/28-...`) if needed.
The single-file BLOB snapshot pattern + delta-buffer approach from §3 is
likely reusable in a pure-numpy implementation.

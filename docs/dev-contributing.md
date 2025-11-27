# Contributing to BeaverDB

BeaverDB follows a **"Simplicity First"** philosophy not just in its API, but also in its development workflow. We minimize tooling overhead and prefer standard Python ecosystem tools.

## Environment Setup

To contribute, you'll need Python 3.12+. We recommend using a virtual environment.

```bash
# 1. Clone the repository
git clone https://github.com/syalia-srl/beaver.git
cd beaver

# 2. Create a virtual environment
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows

# 3. Install in editable mode with ALL dependencies (dev, server, vector, graph)
uv sync
```

## Development Workflow (Makefile)

We use a `makefile` to automate common tasks. You don't need to memorize complex commands.

| Command | Description |
| :--- | :--- |
| `make test-unit` | Runs fast unit tests (Default). Use this during local dev. |
| `make test-all` | Runs **all** tests, including slow integration and concurrency tests. |
| `make format` | Runs `black` to format code and commits the changes. |
| `make docs` | Publishes the documentation to GitHub Pages (requires permissions). |
| `make issues` | Syncs local markdown issues with GitHub Issues (see below). |

## Issue Tracking (File-Based)

BeaverDB uses a unique **"Docs-as-Code"** approach for issue tracking using the `gh-md-issues` extension.

  * **Issues are Files:** Every issue exists as a markdown file in the `issues/` directory (e.g., `issues/31-composable-graph-rag.md`).
  * **Syncing:** We edit these files locally to draft feature plans or update status. Running `make issues` pushes these changes to GitHub Issues and pulls any comments/updates back to your local files.

**Workflow:**

1.  Create a new file `issues/New-Feature.md`.
2.  Write the frontmatter (`title`, `labels`, `state: open`).
3.  Run `make issues` to create it on GitHub.

## Testing Philosophy

Our test suite is divided into strict categories to keep the "Feedback Loop" fast. We use `pytest` markers defined in `pytest.ini`.

### Unit Tests (`pytest -m unit`)

  * **Goal:** Instant feedback (< 1 second).
  * **Scope:** In-memory logic, single-process SQLite, schema validation.
  * **Rule:** NEVER sleep, NEVER perform network I/O, NEVER spawn subprocesses.

### Integration Tests (`pytest -m integration`)

  * **Goal:** Verification of complex interactions.
  * **Scope:** Client-Server communication (FastAPI), File I/O (Blobs), Persistence checks.
  * **Rule:** Can be slower, but must be robust/deterministic.

### Concurrency Tests (`pytest -m concurrency`)

  * **Goal:** Stress testing locks and race conditions.
  * **Scope:** Multiprocessing, locking correctness, high-contention scenarios.
  * **Rule:** These are slow and resource-intensive. Run them only before a PR.

## The Future of BeaverDB

BeaverDB is feature-complete for its core mission: a multi-modal embedded database. The future roadmap focuses on **Architecture** and **Stability** rather than adding new data structures.

### A. The "Async Core" Migration

The single biggest remaining milestone is refactoring the core to be **Async-First**.

  * **Current:** Synchronous core with async wrappers.
  * **Future:** `AsyncBeaverDB` (using `aiosqlite`) as the engine, with a synchronous `BeaverDB` facade on top. This will allow handling thousands of concurrent Pub/Sub listeners and Locks on a single event loop.

### B. Client-Server Parity

We aim for the `BeaverClient` (HTTP) to be a 100% drop-in replacement for `BeaverDB` (Local). Code written for one should run on the other without modification. This allows developers to start local (embedded) and scale to a server deployment effortlessly.

### C. API Stability

We are committed to a stable, Pythonic API. We resist "feature creep." If a feature can be implemented as a plugin or helper function on top of existing primitives (like `DocumentStream` built on `walk`), it belongs there, not in the core.

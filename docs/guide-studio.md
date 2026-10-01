# Beaver Studio

Opening a database to answer a simple question—what is in this file?—should
not change the file. Beaver Studio is a local, read-only inspector that presents
the SQLite data in Beaver terms: modalities, named stores, counts, warnings, and
safe item views.

Studio is an optional feature:

```bash
pip install "beaver-db[studio]"
```

To create a representative local database from a source checkout, run:

```bash
uv run python examples/create_studio_demo.py
uv run beaver studio --db examples/studio-demo.db
```

The generated database is ignored by Git. The script refuses to overwrite an
existing file.

## Inspect before opening a browser

`beaver info` prints the same semantic catalog consumed by Studio:

```bash
beaver info --db app.db
```

Use JSON output in scripts or diagnostics:

```bash
beaver info --db app.db --json | jq '.stores[] | {kind, name, count}'
```

Both forms open an existing database in SQLite read-only mode. They do not
create a missing file, add schema tables, change `user_version`, or clean up
expired values.

## Launch Studio

```bash
beaver studio --db app.db
```

Then open <http://127.0.0.1:8000>. Choose another port when necessary:

```bash
beaver studio --db app.db --port 8765
```

Studio always binds to the loopback interface. It cannot be exposed on another
host and does not provide remote administration.

## What the overview means

The overview reports the database path and size, Beaver and schema versions,
journal mode, WAL size, and SQLite `data_version`. The catalog discovers stores
from Beaver's physical tables, including stores that have never been opened in
the current Python process.

Every known modality appears in the catalog when it contains data:

- dictionaries;
- lists;
- priority queues;
- logs;
- documents;
- vectors;
- graphs;
- blobs;
- channels;
- sketches;
- locks.

Every listed modality has a bounded, read-only viewer. Studio does not force
them into the same shape: vectors and blobs expose summaries before payloads,
graphs expose filtered edges, sketches report approximate state, and locks show
their waiter queue without cleaning it.

Beaver's internal dictionaries, event channels, and manager locks are hidden by
default. The administrative API and `beaver info --include-internal` can include
them for diagnostics.

## Safe item browsing

Studio retrieves bounded pages rather than loading a complete store:

- dictionaries are ordered by key and show TTL expiration without deleting
  expired rows;
- lists show logical indices while keeping fractional ordering keys internal;
- queues are read with `SELECT` and never consumed or reordered;
- logs are ordered by timestamp and can follow commits detected through
  `data_version`, or be limited to an explicit time range;
- documents are ordered by ID and support bounded full-text and fuzzy search.
- vectors show ID, dimension, norm, metadata, and LSH coverage without returning
  components in the list response;
- graphs show ordered edges and accept exact source, target, and label filters;
- blobs show keys, byte sizes, and metadata without reading payloads;
- channels expose stored history and optional time ranges without opening an
  infinite subscription;
- sketches report configuration and approximate cardinality directly from their
  stored representation;
- locks show queue position, age, TTL, expiration, and holder/waiter state
  without deleting expired rows.

Select a row to inspect its JSON representation. Values that are not valid JSON
remain visible as raw text with a warning; one malformed row does not hide the
rest of the page. Stored JSON larger than 64 KiB is represented by a short text
preview, its original byte size, and an explicit truncation warning. Studio does
not place an unbounded value into an API response or browser table.

Pages contain at most 50 rows. JSON deeper than 32 levels and binary values in
JSON columns degrade to bounded previews with warnings. These limits apply
before content reaches the browser.

Encrypted dictionary values are always redacted in the MVP. Studio does not ask
for or store encryption secrets.

## Search documents and inspect index coverage

Choose a document collection to list its IDs and bodies. The search control has
two modes:

- **Full text** uses the collection's FTS5 index. Studio tokenizes punctuation
  before building the FTS query, so input such as `local-first?` is treated as
  user text rather than SQLite query syntax.
- **Fuzzy** uses the collection's trigram index and ranks documents by matching
  trigrams. Queries shorter than three characters return no fuzzy candidates.

The index summary reports how many documents participate in the FTS and fuzzy
indexes. A lower indexed count is visible rather than presented as an empty
search result without explanation; applications may intentionally index a
document with either mode disabled.

Search result pages are bounded. Studio returns an opaque cursor for the next
page and never loads a whole document collection into the browser.

## Inspect vectors, graphs, and binary data

A vector list never contains its component array. Select a row to request its
detail explicitly; Studio returns at most 4,096 float components and labels a
larger vector as truncated. Dimension, norm, metadata, and whether the item has
an LSH entry remain visible in the list.

The graph viewer presents an edge table rather than loading a graph into browser
memory. Source, target, and label filters are exact and remain attached to the
opaque pagination cursor.

A blob list does not fetch payload bytes. Selecting a blob requests a preview of
at most 64 KiB. Declared text and JSON content is decoded as UTF-8; other content
is base64. The response includes the full byte size and states whether the
preview was truncated. Studio does not execute active content.

## Use diagnostics without confusing them with an audit trail

The overview contains three collapsible diagnostic panels:

- **Index diagnostics** reports FTS, fuzzy, field-index, and vector LSH coverage.
- **External SQLite schema** lists non-Beaver tables and views with their column
  definitions, but never executes free-form SQL or reads their rows.
- **Studio operations** retains the latest 200 HTTP operations in process
  memory. Entries contain method, path, status, timing, and error class—not
  query strings or stored values.

Operational entries disappear when Studio stops. They describe requests to the
inspector, not every mutation ever made to the database.

## Read-only failures are deliberate

Writable Beaver connections add missing tables as the schema grows. Studio
cannot perform that repair without violating its read-only guarantee. If an
older compatible database lacks additive tables, Studio refuses to show a
partial catalog and asks you to open the file once with the current Beaver
version in writable mode:

```python
from beaver import BeaverDB

with BeaverDB("app.db"):
    pass
```

Back up the file before any upgrade operation. Legacy 1.x, split-brain, newer,
and incompatible schemas continue to fail loudly and point to the appropriate
migration guidance.

## Current boundaries

Studio does not currently provide:

- editing or destructive operations;
- free-form SQL;
- complete blob downloads;
- rendering graph topology as a node-link diagram;
- sketch membership probes;
- lock release or cleanup controls;
- persistent operational auditing;
- remote Studio sessions;
- SSE or WebSocket streaming.

Stored `db.log()` entries, manager mutation events, and Beaver's Python
diagnostic logs are different data sources. Studio browses stored log
collections; it does not claim to reconstruct every operation performed on the
database.

These boundaries keep the first release useful and predictable: an unfamiliar
Beaver file can be inventoried and sampled without learning the dunder schema or
risking an accidental write.

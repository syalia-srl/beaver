# Search Architecture

**Chapter Outline:**

* **11.1. Vector Search (ANN) Internals**
    * The "Hybrid Index System": Base Index and Delta Index.
    * **Crash-Safe Logging:** How additions and deletions are written to SQLite logs (`_beaver_ann_...` tables).
    * **Background Compaction:** The `compact()` process.
* **11.2. Text Search (FTS & Fuzzy) Internals**
    * **FTS:** How `beaver_fts_index` is a `fts5` virtual table.
    * **Fuzzy Search:** How BeaverDB builds a custom trigram index (`beaver_trigrams` table) and uses Levenshtein distance.

"use strict";

const state = {
  catalog: [],
  current: null,
  cursor: null,
  hasMore: false,
  data_version: null,
  follow: false,
  activeRequest: null,
  documentQuery: "",
  documentSearch: "fts",
  logStart: null,
  logEnd: null,
  graphSource: "",
  graphTarget: "",
  graphLabel: "",
  adminLoaded: false,
};

const elements = {
  facts: document.querySelector("#database-facts"),
  warnings: document.querySelector("#warnings"),
  refreshStatus: document.querySelector("#refresh-status"),
  catalog: document.querySelector("#catalog"),
  storeKind: document.querySelector("#store-kind"),
  resultsTitle: document.querySelector("#results-title"),
  resultStatus: document.querySelector("#result-status"),
  head: document.querySelector("#items-head"),
  body: document.querySelector("#items-body"),
  detail: document.querySelector("#item-detail"),
  loadMore: document.querySelector("#load-more"),
  followControl: document.querySelector("#follow-control"),
  follow: document.querySelector("#follow"),
  documentSearch: document.querySelector("#document-search"),
  documentQuery: document.querySelector("#document-query"),
  documentSearchMode: document.querySelector("#document-search-mode"),
  documentSearchClear: document.querySelector("#document-search-clear"),
  logRange: document.querySelector("#log-range"),
  logStart: document.querySelector("#log-start"),
  logEnd: document.querySelector("#log-end"),
  logRangeClear: document.querySelector("#log-range-clear"),
  indexStatus: document.querySelector("#index-status"),
  graphFilters: document.querySelector("#graph-filters"),
  graphSource: document.querySelector("#graph-source"),
  graphTarget: document.querySelector("#graph-target"),
  graphLabel: document.querySelector("#graph-label"),
  graphFiltersClear: document.querySelector("#graph-filters-clear"),
  diagnosticsOutput: document.querySelector("#diagnostics-output"),
  schemaOutput: document.querySelector("#schema-output"),
  operationsOutput: document.querySelector("#operations-output"),
};

function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = String(text);
  if (className) element.className = className;
  return element;
}

async function api(path) {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.message || `Request failed (${response.status})`);
  return payload;
}

async function runExclusive(task, skipIfBusy = false) {
  if (state.activeRequest) {
    if (skipIfBusy) return;
    try {
      await state.activeRequest;
    } catch (_error) {
      // The operation that owns the error reports it in the interface.
    }
    return runExclusive(task, skipIfBusy);
  }
  const operation = task();
  state.activeRequest = operation;
  try {
    return await operation;
  } finally {
    if (state.activeRequest === operation) state.activeRequest = null;
  }
}

function renderFacts(info) {
  const facts = [
    ["Path", info.path],
    ["Size", `${info.size_bytes.toLocaleString()} bytes`],
    ["Beaver", info.beaver_version],
    ["Schema", info.schema_version],
    ["Journal", info.journal_mode],
    ["WAL size", `${info.wal_size_bytes.toLocaleString()} bytes`],
  ];
  elements.facts.replaceChildren();
  for (const [label, value] of facts) {
    const box = node("div", undefined, "fact");
    box.append(node("dt", label), node("dd", value));
    elements.facts.append(box);
  }
  elements.warnings.replaceChildren();
  for (const warning of info.warnings) {
    elements.warnings.append(node("p", warning));
  }
}

function renderCatalog(entries) {
  elements.catalog.replaceChildren();
  const groups = new Map();
  for (const entry of entries) {
    if (!groups.has(entry.kind)) groups.set(entry.kind, []);
    groups.get(entry.kind).push(entry);
  }
  for (const [kind, stores] of groups) {
    const group = node("section", undefined, "store-group");
    group.append(node("h3", kind));
    for (const store of stores) {
      const button = node("button", undefined, "store-button");
      button.type = "button";
      button.disabled = !store.browsable;
      button.append(node("span", store.name), node("span", store.count ?? "—", "count"));
      button.title = store.warnings.join(" ");
      button.addEventListener("click", () => selectStore(store));
      group.append(button);
    }
    elements.catalog.append(group);
  }
}

function displayValue(value) {
  if (value === null) return "null";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function renderItems(page, append) {
  const items = page.items;
  if (!append) {
    elements.head.replaceChildren();
    elements.body.replaceChildren();
  }
  if (!items.length && !append) {
    elements.resultStatus.textContent = "This store is empty.";
  } else {
    elements.resultStatus.textContent = `${page.total ?? "Unknown"} total item(s)`;
  }
  const columns = [...new Set(items.flatMap((item) => Object.keys(item)))];
  if (columns.length && (!append || !elements.head.children.length)) {
    const row = node("tr");
    for (const column of columns) row.append(node("th", column));
    elements.head.append(row);
  }
  for (const item of items) {
    const row = node("tr");
    row.tabIndex = 0;
    row.setAttribute("aria-label", "Inspect item");
    for (const column of columns) row.append(node("td", displayValue(item[column])));
    const showDetail = () => runExclusive(() => showItemDetail(item));
    row.addEventListener("click", showDetail);
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        showDetail();
      }
    });
    elements.body.append(row);
  }
  state.cursor = page.next_cursor;
  state.hasMore = page.has_more;
  elements.loadMore.hidden = !state.hasMore;
}

async function loadItems(append = false) {
  if (!state.current) return false;
  const params = new URLSearchParams({ name: state.current.name, limit: "50" });
  if (append && state.cursor) params.set("cursor", state.cursor);
  if (state.current.kind === "docs" && state.documentQuery) {
    params.set("query", state.documentQuery);
    params.set("search", state.documentSearch);
  }
  if (state.current.kind === "log" || state.current.kind === "channel") {
    if (state.logStart !== null) params.set("start", String(state.logStart));
    if (state.logEnd !== null) params.set("end", String(state.logEnd));
  }
  if (state.current.kind === "graph") {
    if (state.graphSource) params.set("source", state.graphSource);
    if (state.graphTarget) params.set("target", state.graphTarget);
    if (state.graphLabel) params.set("label", state.graphLabel);
  }
  try {
    elements.resultStatus.textContent = "Loading…";
    const page = await api(`/admin/v1/stores/${encodeURIComponent(state.current.kind)}/items?${params}`);
    renderItems(page, append);
    return true;
  } catch (error) {
    elements.resultStatus.textContent = error.message;
    return false;
  }
}

async function showItemDetail(item) {
  if (!state.current) return;
  const identifier = item.id ?? item.key;
  if ((state.current.kind === "vectors" || state.current.kind === "blob") && identifier !== undefined) {
    const params = new URLSearchParams({ name: state.current.name, id: String(identifier) });
    try {
      elements.detail.textContent = "Loading bounded detail…";
      const detail = await api(`/admin/v1/stores/${state.current.kind}/item?${params}`);
      elements.detail.textContent = JSON.stringify(detail, null, 2);
    } catch (error) {
      elements.detail.textContent = error.message;
    }
    return;
  }
  elements.detail.textContent = JSON.stringify(item, null, 2);
}

async function loadAdminPanels(full = false) {
  try {
    if (full || !state.adminLoaded) {
      const [diagnostics, schema] = await Promise.all([
        api("/admin/v1/diagnostics"),
        api("/admin/v1/schema"),
      ]);
      elements.diagnosticsOutput.textContent = JSON.stringify(diagnostics, null, 2);
      elements.schemaOutput.textContent = schema.length
        ? JSON.stringify(schema, null, 2)
        : "No external tables or views.";
      state.adminLoaded = true;
    }
    const operations = await api("/admin/v1/operations");
    elements.operationsOutput.textContent = operations.length
      ? JSON.stringify(operations.slice(-20), null, 2)
      : "No Studio operations recorded yet.";
  } catch (error) {
    elements.diagnosticsOutput.textContent = error.message;
  }
}

async function loadIndexes() {
  elements.indexStatus.replaceChildren();
  elements.indexStatus.hidden = state.current?.kind !== "docs";
  if (state.current?.kind !== "docs") return;
  try {
    const params = new URLSearchParams({ name: state.current.name });
    const summary = await api(`/admin/v1/stores/docs/indexes?${params}`);
    elements.indexStatus.append(
      node("p", `Indexes: FTS ${summary.fts_items}/${summary.items} · fuzzy ${summary.fuzzy_items}/${summary.items}`),
    );
    for (const field of summary.field_indexes) {
      elements.indexStatus.append(
        node("p", `Field ${field.field}: ${field.complete ? "complete" : "incomplete"} (${field.rows} rows)`),
      );
    }
    for (const warning of summary.warnings) {
      elements.indexStatus.append(node("p", warning));
    }
  } catch (error) {
    elements.indexStatus.append(node("p", error.message));
  }
}

async function catchUpLog(pollTail = false) {
  if (pollTail && !(await loadItems(true))) return;
  while (state.follow && state.current?.kind === "log" && state.hasMore) {
    if (!(await loadItems(true))) return;
  }
}

async function selectStore(store) {
  await runExclusive(async () => {
    const changedStore =
      state.current?.kind !== store.kind || state.current?.name !== store.name;
    state.current = store;
    state.cursor = null;
    state.hasMore = false;
    if (changedStore) {
      state.documentQuery = "";
      state.documentSearch = "fts";
      state.logStart = null;
      state.logEnd = null;
      state.graphSource = "";
      state.graphTarget = "";
      state.graphLabel = "";
      elements.documentQuery.value = "";
      elements.documentSearchMode.value = "fts";
      elements.logStart.value = "";
      elements.logEnd.value = "";
      elements.graphSource.value = "";
      elements.graphTarget.value = "";
      elements.graphLabel.value = "";
    }
    elements.storeKind.textContent = store.kind;
    elements.resultsTitle.textContent = store.name;
    elements.followControl.hidden = store.kind !== "log";
    elements.documentSearch.hidden = store.kind !== "docs";
    elements.logRange.hidden = store.kind !== "log" && store.kind !== "channel";
    elements.graphFilters.hidden = store.kind !== "graph";
    elements.indexStatus.hidden = store.kind !== "docs";
    if (store.kind !== "log") {
      state.follow = false;
      elements.follow.checked = false;
    }
    elements.detail.textContent = "Select a row to inspect its JSON.";
    await loadItems(false);
    await loadIndexes();
    if (state.follow && store.kind === "log") await catchUpLog();
  });
}

async function refresh() {
  await runExclusive(async () => {
    try {
      const info = await api("/admin/v1/info");
      const changed = state.data_version !== null && info.data_version !== state.data_version;
      state.data_version = info.data_version;
      renderFacts(info);
      elements.refreshStatus.textContent = `Data version ${info.data_version}`;
      await loadAdminPanels(changed);
      if (!state.catalog.length || changed) {
        state.catalog = await api("/admin/v1/catalog");
        renderCatalog(state.catalog);
      }
      if (state.current?.kind === "log" && state.follow) {
        if (changed) await catchUpLog(true);
        else if (state.hasMore) await catchUpLog();
      } else if (changed && state.current) {
        await loadItems(false);
      } else if (state.current?.kind === "lock") {
        await loadItems(false);
      }
    } catch (error) {
      elements.refreshStatus.textContent = error.message;
    }
  }, true);
}

elements.loadMore.addEventListener("click", () => runExclusive(() => loadItems(true)));
elements.follow.addEventListener("change", () => {
  state.follow = elements.follow.checked;
  elements.refreshStatus.textContent = state.follow ? "Following log changes" : "Follow paused";
  if (state.follow) runExclusive(() => catchUpLog());
});

elements.documentSearch.addEventListener("submit", (event) => {
  event.preventDefault();
  state.documentQuery = elements.documentQuery.value.trim();
  state.documentSearch = elements.documentSearchMode.value;
  state.cursor = null;
  runExclusive(() => loadItems(false));
});

elements.documentSearchClear.addEventListener("click", () => {
  elements.documentQuery.value = "";
  state.documentQuery = "";
  state.cursor = null;
  runExclusive(() => loadItems(false));
});

function inputTimestamp(value) {
  if (!value) return null;
  return new Date(value).getTime() / 1000;
}

elements.logRange.addEventListener("submit", (event) => {
  event.preventDefault();
  state.logStart = inputTimestamp(elements.logStart.value);
  state.logEnd = inputTimestamp(elements.logEnd.value);
  state.cursor = null;
  runExclusive(() => loadItems(false));
});

elements.logRangeClear.addEventListener("click", () => {
  elements.logStart.value = "";
  elements.logEnd.value = "";
  state.logStart = null;
  state.logEnd = null;
  state.cursor = null;
  runExclusive(() => loadItems(false));
});

elements.graphFilters.addEventListener("submit", (event) => {
  event.preventDefault();
  state.graphSource = elements.graphSource.value.trim();
  state.graphTarget = elements.graphTarget.value.trim();
  state.graphLabel = elements.graphLabel.value.trim();
  state.cursor = null;
  runExclusive(() => loadItems(false));
});

elements.graphFiltersClear.addEventListener("click", () => {
  elements.graphSource.value = "";
  elements.graphTarget.value = "";
  elements.graphLabel.value = "";
  state.graphSource = "";
  state.graphTarget = "";
  state.graphLabel = "";
  state.cursor = null;
  runExclusive(() => loadItems(false));
});

refresh();
window.setInterval(refresh, 2000);

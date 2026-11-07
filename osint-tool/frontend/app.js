const API_BASE = "http://localhost:8000";
const API_KEY_STORAGE = "osint_api_key";

function getApiKey() {
  try {
    return localStorage.getItem(API_KEY_STORAGE) || "";
  } catch (err) {
    return "";
  }
}

function authHeaders(extra = {}) {
  const headers = { ...extra };
  const key = getApiKey();
  if (key) {
    headers["X-API-Key"] = key;
  }
  return headers;
}

const panels = {};

function getPanel(tabName) {
  if (!panels[tabName]) {
    const section = document.getElementById(`panel-${tabName}`);
    panels[tabName] = {
      root: section,
      form: section.querySelector(".search-form"),
      input: section.querySelector(".search-form input"),
      button: section.querySelector(".search-form button"),
      spinner: section.querySelector(".spinner"),
      errorBox: section.querySelector(".error-box"),
      summary: section.querySelector(".summary"),
      results: section.querySelector(".results"),
      controller: null,
    };
  }
  return panels[tabName];
}

function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = value == null ? "" : String(value);
  return div.innerHTML;
}

function activateTab(name) {
  document.querySelectorAll(".tab").forEach((btn) => {
    const active = btn.dataset.tab === name;
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-selected", active ? "true" : "false");
  });
  document.querySelectorAll(".panel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === `panel-${name}`);
  });
  if (name === "catalog") {
    loadCatalogOnce();
  }
}

function setLoading(panel, isLoading) {
  panel.spinner.classList.toggle("hidden", !isLoading);
  panel.button.disabled = isLoading;
}

function showError(panel, message) {
  panel.errorBox.textContent = `[ERROR] ${message}`;
  panel.errorBox.classList.remove("hidden");
}

function clearPanel(panel) {
  panel.errorBox.classList.add("hidden");
  panel.errorBox.textContent = "";
  panel.summary.innerHTML = "";
  panel.results.innerHTML = "";
}

function buildCard(item) {
  const card = document.createElement("div");
  card.className = "card";

  const head = document.createElement("div");
  head.className = "card-head";

  const title = document.createElement("h3");
  title.className = "card-title";
  title.textContent =
    item.platform || item.name || item.site || item.source || "Unknown";
  head.appendChild(title);

  const status = item.status || "found";
  const badge = document.createElement("span");
  badge.className = `badge ${status}`;
  badge.textContent = status;
  head.appendChild(badge);
  card.appendChild(head);

  if (item.kind === "post") {
    const tag = document.createElement("span");
    tag.className = "tag";
    tag.textContent = "post";
    head.appendChild(tag);
  }

  const url = item.url || item.profile_url || "";
  if (url && /^https?:\/\//i.test(url)) {
    const link = document.createElement("a");
    link.className = "card-url";
    link.href = url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = url;
    card.appendChild(link);
  }

  const metaParts = [];
  if (item.sources && Array.isArray(item.sources) && item.sources.length) {
    metaParts.push(
      "detected by: " +
        item.sources
          .map((source) => `<span class="tag">${escapeHtml(source)}</span>`)
          .join("")
    );
  }
  if (item.title) {
    metaParts.push(escapeHtml(item.title));
  }
  if (item.confidence) {
    metaParts.push(
      `account exists: <span class="tag">${escapeHtml(item.confidence)} confidence</span>`
    );
  }
  if (item.match) {
    metaParts.push(`name match: <span class="tag">${escapeHtml(item.match)}</span>`);
  }
  if (item.info) {
    metaParts.push(escapeHtml(item.info));
  }
  if (item.query) {
    metaParts.push(`query: ${escapeHtml(item.query)}`);
  }
  if (metaParts.length) {
    const meta = document.createElement("div");
    meta.className = "card-meta";
    meta.innerHTML = metaParts.join("<br />");
    card.appendChild(meta);
  }

  return card;
}

function reportMarkdown(data) {
  const lines = [
    `# OSINT report: ${data.query}`,
    "",
    `Generated: ${new Date().toISOString()}`,
    "",
    "## Results",
    "",
  ];
  const exportItems = [...(data.posts || []), ...data.results];
  exportItems.forEach((item) => {
    const title = item.platform || item.name || item.site || "Unknown";
    const url = item.url || item.profile_url;
    lines.push(`### ${title} (${item.status || "found"})`);
    if (url) lines.push(`- URL: ${url}`);
    if (item.title) lines.push(`- Title: ${item.title}`);
    if (item.confidence) lines.push(`- Account exists: ${item.confidence} confidence`);
    if (item.match) lines.push(`- Name match: ${item.match}`);
    if (item.info) lines.push(`- ${item.info}`);
    lines.push("");
  });
  if (Array.isArray(data.warnings) && data.warnings.length) {
    lines.push("## Warnings", "");
    data.warnings.forEach((warning) => lines.push(`- ${warning}`));
    lines.push("");
  }
  if (Array.isArray(data.links) && data.links.length) {
    lines.push("## Check manually (not verified)", "");
    data.links.forEach((link) => lines.push(`- ${link.label}: ${link.url}`));
    lines.push("");
  }
  if (data.notice) lines.push(`> ${data.notice}`);
  return lines.join("\n");
}

function downloadReport(data, extension) {
  const isJson = extension === "json";
  const blob = new Blob(
    [isJson ? JSON.stringify(data, null, 2) : reportMarkdown(data)],
    { type: isJson ? "application/json" : "text/markdown" }
  );
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  const safeName = String(data.query).replace(/[^A-Za-z0-9._-]+/g, "_").slice(0, 60);
  link.download = `osint-${safeName}.${extension}`;
  link.click();
  URL.revokeObjectURL(link.href);
}

function buildActionButton(label, onClick) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "chip";
  button.textContent = label;
  button.addEventListener("click", onClick);
  return button;
}

function pivotTo(pivot) {
  const tabByType = { username: "username", company: "company", domain: "domain", ip: "domain" };
  const tab = tabByType[pivot.type] || "domain";
  activateTab(tab);
  const panel = getPanel(tab);
  panel.input.value = pivot.value;
  panel.form.requestSubmit();
}

function buildToolbar(data) {
  const toolbar = document.createElement("div");
  toolbar.className = "toolbar";
  if (data.results.length) {
    const exports = document.createElement("div");
    exports.className = "chip-row";
    exports.appendChild(buildActionButton("Export MD", () => downloadReport(data, "md")));
    exports.appendChild(buildActionButton("Export JSON", () => downloadReport(data, "json")));
    toolbar.appendChild(exports);
  }
  if (Array.isArray(data.pivots) && data.pivots.length) {
    const pivots = document.createElement("div");
    pivots.className = "chip-row";
    const label = document.createElement("span");
    label.textContent = "pivot:";
    pivots.appendChild(label);
    data.pivots.forEach((pivot) => {
      pivots.appendChild(buildActionButton(pivot.value, () => pivotTo(pivot)));
    });
    toolbar.appendChild(pivots);
  }
  if (Array.isArray(data.links) && data.links.length) {
    const links = document.createElement("div");
    links.className = "chip-row";
    const label = document.createElement("span");
    label.textContent = "check manually (login required, not verified):";
    links.appendChild(label);
    data.links.forEach((item) => {
      const link = document.createElement("a");
      link.className = "chip";
      link.href = item.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = item.label;
      links.appendChild(link);
    });
    toolbar.appendChild(links);
  }
  if (data.notice) {
    const notice = document.createElement("div");
    notice.className = "notice";
    notice.textContent = data.notice;
    toolbar.appendChild(notice);
  }
  return toolbar;
}

function renderResults(panel, data) {
  const queryText = data.query != null ? `"${data.query}"` : "your query";
  const cachedLabel = data.cached
    ? ' <span class="tag">cached</span>'
    : "";
  panel.summary.innerHTML = `<strong>${data.count}</strong> result${
    data.count === 1 ? "" : "s"
  } for ${escapeHtml(queryText)}${cachedLabel}`;
  panel.results.appendChild(buildToolbar(data));

  if (Array.isArray(data.warnings) && data.warnings.length) {
    const warnings = document.createElement("div");
    warnings.className = "warnings";
    const head = document.createElement("div");
    head.className = "warnings-head";
    head.textContent = `${data.warnings.length} note${
      data.warnings.length === 1 ? "" : "s"
    } (skipped or unavailable sources)`;
    warnings.appendChild(head);
    data.warnings.forEach((warning) => {
      const item = document.createElement("div");
      item.className = "warning-item";
      item.textContent = warning;
      warnings.appendChild(item);
    });
    panel.results.appendChild(warnings);
  }

  if (Array.isArray(data.posts) && data.posts.length) {
    const header = document.createElement("div");
    header.className = "section-head";
    header.textContent = `Public posts (${data.posts.length})`;
    panel.results.appendChild(header);
    data.posts.forEach((post, index) => {
      const card = buildCard(post);
      card.style.animationDelay = `${Math.min(index * 40, 400)}ms`;
      panel.results.appendChild(card);
    });
    if (data.results.length) {
      const divider = document.createElement("div");
      divider.className = "section-head";
      divider.textContent = `Profiles (${data.results.length})`;
      panel.results.appendChild(divider);
    }
  }

  if (!data.results.length && !(Array.isArray(data.posts) && data.posts.length)) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent =
      data.message ||
      "No public traces found. The target may not exist on scanned platforms.";
    panel.results.appendChild(empty);
    return;
  }

  data.results.forEach((item, index) => {
    const card = buildCard(item);
    card.style.animationDelay = `${Math.min(index * 40, 400)}ms`;
    panel.results.appendChild(card);
  });
}

const JOB_POLL_INTERVAL_MS = 1500;
const JOB_MAX_WAIT_MS = 20 * 60 * 1000;
const DEFAULT_SPINNER_TEXT = "Searching public profiles...";

function setSpinnerText(panel, text) {
  const label = panel.spinner.querySelector("span");
  if (label) {
    label.textContent = text;
  }
}

function sleep(ms, signal) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    function onAbort() {
      clearTimeout(timer);
      reject(new DOMException("Aborted", "AbortError"));
    }
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

async function requestJson(url, options) {
  const response = await fetch(url, options);
  let data = null;
  try {
    data = await response.json();
  } catch (parseError) {
    throw new Error(`Backend returned a non-JSON response (HTTP ${response.status}).`);
  }
  if (!response.ok) {
    const error = new Error(
      data.message || data.detail || `Request failed with HTTP ${response.status}.`
    );
    error.jobsUnavailable = response.status === 503 || response.status === 404;
    throw error;
  }
  return data;
}

async function startJob(category, query, signal) {
  return requestJson(`${API_BASE}/api/jobs`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ category, query }),
    signal,
  });
}

async function waitForJob(jobId, signal) {
  const deadline = Date.now() + JOB_MAX_WAIT_MS;
  while (Date.now() < deadline) {
    const data = await requestJson(`${API_BASE}/api/jobs/${jobId}`, {
      headers: authHeaders(),
      signal,
    });
    if (data.status === "complete") {
      return data.result;
    }
    if (data.status === "failed") {
      throw new Error(data.message || "Investigation job failed.");
    }
    await sleep(JOB_POLL_INTERVAL_MS, signal);
  }
  throw new Error("Investigation is taking too long. Try again later.");
}

async function runSyncSearch(endpoint, query, signal) {
  const data = await requestJson(`${API_BASE}${endpoint}`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ query }),
    signal,
  });
  if (data.status !== "success") {
    throw new Error(data.message || data.detail || "Search failed.");
  }
  return data;
}

async function handleSubmit(event) {
  event.preventDefault();
  const panel = getPanel(event.currentTarget.closest(".panel").id.replace("panel-", ""));
  const query = panel.input.value.trim();
  const endpoint = panel.form.dataset.endpoint;
  const category = panel.form.dataset.category;

  clearPanel(panel);
  if (!query) {
    showError(panel, "Please enter a value before searching.");
    return;
  }

  if (panel.controller) {
    panel.controller.abort();
  }
  panel.controller = new AbortController();
  const signal = panel.controller.signal;

  setLoading(panel, true);
  setSpinnerText(panel, DEFAULT_SPINNER_TEXT);
  try {
    let data;
    if (category) {
      setSpinnerText(panel, "Queued — deep scan may take several minutes...");
      try {
        const job = await startJob(category, query, signal);
        data = await waitForJob(job.job_id, signal);
      } catch (jobError) {
        if (jobError.name === "AbortError") return;
        if (!jobError.jobsUnavailable) {
          throw jobError;
        }
        setSpinnerText(panel, DEFAULT_SPINNER_TEXT);
        data = await runSyncSearch(endpoint, query, signal);
      }
    } else {
      data = await runSyncSearch(endpoint, query, signal);
    }

    if (!data || data.status !== "success") {
      showError(panel, (data && (data.message || data.detail)) || "Search failed.");
      return;
    }

    renderResults(panel, data);
  } catch (err) {
    if (err.name === "AbortError") return;
    showError(
      panel,
      err.message ||
        `Could not reach the backend at ${API_BASE}. Make sure it is running (docker-compose up).`
    );
  } finally {
    setSpinnerText(panel, DEFAULT_SPINNER_TEXT);
    setLoading(panel, false);
  }
}

async function checkApiStatus() {
  const el = document.getElementById("api-status");
  try {
    const response = await fetch(`${API_BASE}/health`, { method: "GET" });
    const data = await response.json();
    if (response.ok && data.status === "ok") {
      el.textContent = "[API ONLINE]";
      el.classList.add("online");
      el.classList.remove("offline");
      return;
    }
    throw new Error("unhealthy");
  } catch (err) {
    el.textContent = "[API OFFLINE]";
    el.classList.add("offline");
    el.classList.remove("online");
  }
}

document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => activateTab(btn.dataset.tab));
});

document.querySelectorAll(".search-form").forEach((form) => {
  form.addEventListener("submit", handleSubmit);
});

let catalogItems = [];
let catalogLoaded = false;

function renderCatalog(categories) {
  const list = document.getElementById("catalog-list");
  list.innerHTML = "";
  categories.forEach((category) => {
    const heading = document.createElement("h2");
    heading.className = "catalog-heading";
    heading.textContent = category.name;
    list.appendChild(heading);

    const grid = document.createElement("div");
    grid.className = "catalog-grid";
    grid.dataset.category = category.name.toLowerCase();
    category.items.forEach((item) => {
      const card = document.createElement("div");
      card.className = "card catalog-card";
      card.dataset.search = `${item.name} ${item.note}`.toLowerCase();

      const link = document.createElement("a");
      link.className = "card-title catalog-link";
      link.href = item.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = item.name;
      card.appendChild(link);

      const meta = document.createElement("div");
      meta.className = "card-meta";
      meta.textContent = item.note;
      card.appendChild(meta);
      grid.appendChild(card);
    });
    list.appendChild(grid);
  });
}

function filterCatalog(query) {
  const needle = query.trim().toLowerCase();
  document.querySelectorAll("#catalog-list .catalog-card").forEach((card) => {
    const match =
      !needle || (card.dataset.search || "").includes(needle);
    card.classList.toggle("hidden", !match);
  });
  document.querySelectorAll("#catalog-list .catalog-grid").forEach((grid) => {
    const visible = grid.querySelectorAll(".catalog-card:not(.hidden)").length;
    grid.classList.toggle("hidden", visible === 0);
  });
  document.querySelectorAll("#catalog-list .catalog-heading").forEach((h) => {
    const grid = h.nextElementSibling;
    if (grid) {
      h.classList.toggle(
        "hidden",
        !grid || grid.querySelectorAll(".catalog-card:not(.hidden)").length === 0
      );
    }
  });
}

async function loadCatalogOnce() {
  if (catalogLoaded) return;
  const list = document.getElementById("catalog-list");
  try {
    const response = await fetch(`${API_BASE}/api/catalog`, {
      headers: authHeaders(),
    });
    const data = await response.json();
    if (!response.ok || data.status !== "success") {
      throw new Error(data.message || data.detail || "failed");
    }
    catalogItems = data.categories;
    renderCatalog(catalogItems);
    catalogLoaded = true;
  } catch (err) {
    list.innerHTML =
      '<div class="empty-state">Could not load the catalog. Is the backend running?</div>';
  }
}

document.getElementById("catalog-filter").addEventListener("input", (event) => {
  filterCatalog(event.currentTarget.value);
});

checkApiStatus();
setInterval(checkApiStatus, 30000);

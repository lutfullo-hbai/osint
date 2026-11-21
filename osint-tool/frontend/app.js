// Override per deployment with <meta name="osint-api-base" content="..."> in
// index.html (or window.OSINT_API_BASE set before this script loads).
const API_BASE = (
  window.OSINT_API_BASE ||
  document.querySelector('meta[name="osint-api-base"]')?.content ||
  "http://localhost:8000"
).replace(/\/+$/, "");
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

// ---- Local AI (Ollama + Qwen) — runs in the browser, data stays on your machine ----
const OLLAMA_URL_KEY = "osint_ollama_url";
const OLLAMA_MODEL_KEY = "osint_ollama_model";
const OLLAMA_VISION_KEY = "osint_ollama_vision_model";

// Server-provided defaults (from backend .env); localStorage still overrides.
const AI_DEFAULTS = {
  url: "http://127.0.0.1:11434",
  model: "qwen2.5:7b",
  vision: "qwen2.5vl:7b",
};

async function loadAiDefaults() {
  try {
    const response = await fetch(`${API_BASE}/api/config`, { headers: authHeaders() });
    if (!response.ok) return;
    const cfg = (await response.json()).ollama || {};
    if (cfg.url) AI_DEFAULTS.url = cfg.url;
    if (cfg.model) AI_DEFAULTS.model = cfg.model;
    if (cfg.vision_model) AI_DEFAULTS.vision = cfg.vision_model;
  } catch (err) {
    /* keep built-in defaults */
  }
}

function ollamaConfig() {
  let url = AI_DEFAULTS.url;
  let model = AI_DEFAULTS.model;
  try {
    url = localStorage.getItem(OLLAMA_URL_KEY) || url;
    model = localStorage.getItem(OLLAMA_MODEL_KEY) || model;
  } catch (err) {
    /* ignore */
  }
  let vision = AI_DEFAULTS.vision;
  try {
    vision = localStorage.getItem(OLLAMA_VISION_KEY) || vision;
  } catch (err) {
    /* ignore */
  }
  return { url, model, vision };
}

function findingsForPrompt(data) {
  const items = [...(data.posts || []), ...(data.results || [])].slice(0, 40);
  return items
    .map((item) => {
      const title = item.platform || item.name || item.site || "item";
      const parts = [title];
      if (item.title && item.title !== title) parts.push(item.title);
      if (item.confidence) parts.push(`(${item.confidence} confidence)`);
      if (item.status && item.status !== "found") parts.push(`[${item.status}]`);
      const url = item.url || item.profile_url;
      if (url) parts.push(url);
      if (item.info) parts.push("— " + String(item.info).slice(0, 280));
      return "- " + parts.join(" ");
    })
    .join("\n");
}

async function analyzeWithAI(data, container, button) {
  const { url, model } = ollamaConfig();
  button.disabled = true;
  button.textContent = "Analyzing…";
  container.classList.remove("hidden");
  container.textContent = "Running local model (" + model + ")…";

  const prompt =
    `OSINT investigation — category: ${data.category || "-"}, query: "${data.query}".\n\n` +
    `Findings:\n${findingsForPrompt(data)}\n\n` +
    `Write a short intelligence summary (4-6 sentences): what was found, which ` +
    `results corroborate each other, likely false positives or contradictions, an ` +
    `overall confidence (low/medium/high), and the single best next step. ` +
    `Only use the findings above. Do not invent facts.`;

  try {
    const response = await fetch(`${url}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model,
        messages: [
          {
            role: "system",
            content:
              "You are a careful OSINT analyst. Be concise and factual, cite " +
              "sources by platform name, never fabricate. A matching username or " +
              "name is not proof of identity.",
          },
          { role: "user", content: prompt },
        ],
        stream: false,
        options: { temperature: 0.2 },
      }),
    });
    if (!response.ok) {
      throw new Error(`Ollama returned HTTP ${response.status}`);
    }
    const payload = await response.json();
    const text = (payload.message && payload.message.content) || "(empty response)";
    container.textContent = "";
    text
      .split(/\n{2,}/)
      .filter((p) => p.trim())
      .forEach((para) => {
        const el = document.createElement("p");
        el.textContent = para.trim();
        container.appendChild(el);
      });
  } catch (err) {
    container.textContent =
      `Could not reach a local model at ${url}. Make sure Ollama is running ` +
      `with a Qwen model (ollama pull qwen2.5:7b). ` +
      `Override with localStorage ${OLLAMA_URL_KEY} / ${OLLAMA_MODEL_KEY}. [${err.message}]`;
  } finally {
    button.disabled = false;
    button.textContent = "AI Summary";
  }
}

async function analyzeVision(data, container, button) {
  const { url, vision } = ollamaConfig();
  if (!data.preview_b64) {
    container.classList.remove("hidden");
    container.textContent = "No image preview available to analyze.";
    return;
  }
  button.disabled = true;
  button.textContent = "Looking…";
  container.classList.remove("hidden");
  container.textContent = "Running local vision model (" + vision + ")…";

  const prompt =
    "Describe this image for an OSINT geolocation analysis. List: visible text / " +
    "signs (and language), landmarks or notable buildings, vehicles and licence-plate " +
    "style, terrain and vegetation, clothing, and any clue to the country or city. " +
    "State what you are unsure about. Do not invent details.";

  try {
    const response = await fetch(`${url}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: vision,
        messages: [{ role: "user", content: prompt, images: [data.preview_b64] }],
        stream: false,
        options: { temperature: 0.2 },
      }),
    });
    if (!response.ok) throw new Error(`Ollama returned HTTP ${response.status}`);
    const payload = await response.json();
    const text = (payload.message && payload.message.content) || "(empty response)";
    container.textContent = "";
    text.split(/\n{2,}/).filter((p) => p.trim()).forEach((para) => {
      const el = document.createElement("p");
      el.textContent = para.trim();
      container.appendChild(el);
    });
  } catch (err) {
    container.textContent =
      `Could not reach a local vision model at ${url}. Pull one first, e.g. ` +
      `"ollama pull qwen2.5vl:7b" (or llava / moondream), then set ` +
      `localStorage ${OLLAMA_VISION_KEY}. [${err.message}]`;
  } finally {
    button.disabled = false;
    button.textContent = "AI Vision";
  }
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
  document.querySelectorAll(".tab[data-tab]").forEach((btn) => {
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
  if (name === "cases") {
    loadCases();
  }
  if (name === "watch") {
    loadWatches();
  }
  if (name === "data") {
    loadDataPanel();
  }
}

// ---- Watch (scheduled monitoring) ----

async function watchApi(path, options = {}) {
  return requestJson(`${API_BASE}/api/watches${path}`, {
    headers: authHeaders({ "Content-Type": "application/json" }),
    ...options,
  });
}

function watchError(message) {
  const box = document.querySelector("#panel-watch .error-box");
  if (!box) return;
  box.textContent = message ? `[ERROR] ${message}` : "";
  box.classList.toggle("hidden", !message);
}

async function handleCreateWatch(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const name = form.name.value.trim();
  const category = document.getElementById("watch-category").value;
  const query = form.query.value.trim();
  const interval = parseInt(document.getElementById("watch-interval").value, 10);
  watchError("");
  if (!name || !query) {
    watchError("Please fill in a name and a target.");
    return;
  }
  try {
    const data = await watchApi("", {
      method: "POST",
      body: JSON.stringify({ name, category, query, interval_minutes: interval }),
    });
    if (!data || data.status !== "success") {
      watchError((data && data.message) || "Could not create watch.");
      return;
    }
    form.query.value = "";
    form.name.value = "";
    loadWatches();
  } catch (err) {
    watchError(err.message || "Could not reach the backend.");
  }
}

async function loadWatches() {
  const list = document.getElementById("watch-list");
  if (!list) return;
  list.innerHTML = '<div class="empty-state">Loading watches...</div>';
  try {
    const data = await watchApi("");
    const watches = (data && data.watches) || [];
    if (!watches.length) {
      list.innerHTML =
        '<div class="empty-state">No watches yet. Add one above to monitor a public target over time.</div>';
      return;
    }
    list.innerHTML = "";
    watches.forEach((w) => list.appendChild(buildWatchCard(w)));
  } catch (err) {
    list.innerHTML = `<div class="empty-state">Could not load watches: ${escapeHtml(err.message || "")}</div>`;
  }
}

function buildWatchCard(w) {
  const card = document.createElement("div");
  card.className = "card watch-card";

  const head = document.createElement("div");
  head.className = "card-head";
  const title = document.createElement("h3");
  title.className = "card-title";
  title.textContent = w.name;
  head.appendChild(title);
  const badge = document.createElement("span");
  const st = (w.last_status || "pending").split(":")[0].trim();
  badge.className = `badge watch-${st.replace(/\s+/g, "-")}`;
  badge.textContent = w.active ? st : "paused";
  head.appendChild(badge);
  card.appendChild(head);

  const meta = document.createElement("div");
  meta.className = "card-meta";
  const everyMin = w.interval_minutes;
  const every = everyMin % 1440 === 0 ? `${everyMin / 1440}d`
    : everyMin % 60 === 0 ? `${everyMin / 60}h` : `${everyMin}m`;
  meta.innerHTML =
    `<span class="tag">${escapeHtml(w.category)}</span> ${escapeHtml(w.query)}` +
    `<br />every ${every} · ` +
    (w.last_checked_at ? `last checked ${escapeHtml(w.last_checked_at.replace("T", " "))}` : "not checked yet") +
    ` · ${w.event_count || 0} change${w.event_count === 1 ? "" : "s"}`;
  card.appendChild(meta);

  if (w.last_event_at) {
    const le = document.createElement("div");
    le.className = "card-meta";
    le.textContent = `last change: ${w.last_event_at.replace("T", " ")}`;
    card.appendChild(le);
  }

  const actions = document.createElement("div");
  actions.className = "chip-row";
  actions.appendChild(buildActionButton("Run now", async () => {
    watchError("");
    try {
      await watchApi(`/${w.id}/run`, { method: "POST" });
      setTimeout(loadWatches, 1200);
    } catch (err) {
      watchError(err.message || "Run failed.");
    }
  }));
  actions.appendChild(buildActionButton(w.active ? "Pause" : "Resume", async () => {
    try {
      await watchApi(`/${w.id}`, { method: "PATCH", body: JSON.stringify({ active: !w.active }) });
      loadWatches();
    } catch (err) {
      watchError(err.message || "Toggle failed.");
    }
  }));
  actions.appendChild(buildActionButton("History", () => openWatch(w.id)));
  const del = buildActionButton("Delete", async () => {
    try {
      await watchApi(`/${w.id}`, { method: "DELETE" });
      loadWatches();
    } catch (err) {
      watchError(err.message || "Delete failed.");
    }
  });
  del.classList.add("chip-danger");
  actions.appendChild(del);
  card.appendChild(actions);

  const events = document.createElement("div");
  events.className = "watch-events hidden";
  events.id = `watch-events-${w.id}`;
  card.appendChild(events);
  return card;
}

async function openWatch(watchId) {
  const container = document.getElementById(`watch-events-${watchId}`);
  if (!container) return;
  if (!container.classList.contains("hidden")) {
    container.classList.add("hidden");
    return;
  }
  container.classList.remove("hidden");
  container.innerHTML = "Loading history...";
  try {
    const data = await watchApi(`/${watchId}`);
    const events = (data.watch && data.watch.events) || [];
    if (!events.length) {
      container.innerHTML = '<div class="empty-state">No changes recorded yet.</div>';
      return;
    }
    container.innerHTML = "";
    events.forEach((e) => {
      const row = document.createElement("div");
      row.className = "watch-event";
      row.innerHTML = `<span class="watch-event-time">${escapeHtml(e.created_at.replace("T", " "))}</span> ${escapeHtml(e.summary)}`;
      container.appendChild(row);
    });
  } catch (err) {
    container.innerHTML = `<div class="empty-state">Could not load history: ${escapeHtml(err.message || "")}</div>`;
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
  if (item.signal === "registration") {
    // a sign-up form said "taken": a lead, not a confirmed account
    badge.className = "badge unconfirmed";
    badge.textContent = "signal · unconfirmed";
    badge.title = "The site's sign-up check reports this address as taken. No profile was seen.";
  }
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
  if (item.retrieved_at) {
    metaParts.push(`<span class="retrieved">retrieved ${escapeHtml(formatRetrieved(item.retrieved_at))}</span>`);
  }
  if (metaParts.length) {
    const meta = document.createElement("div");
    meta.className = "card-meta";
    meta.innerHTML = metaParts.join("<br />");
    card.appendChild(meta);
  }

  return card;
}

// 8.1: when the source was asked (UTC), as "2026-11-19 14:05 UTC"
function formatRetrieved(value) {
  return String(value || "").slice(0, 16).replace("T", " ") + " UTC";
}

function reportMarkdown(data) {
  const lines = [
    `# OSINT report: ${data.query}`,
    "",
    `- Tool: NEXUS OSINT Console`,
    `- Category: ${data.category || "-"}`,
    `- Generated: ${new Date().toISOString()}`,
    `- Results: ${data.results.length}` +
      (data.cached ? " (served from cache)" : ""),
    "",
    "> Open-source intelligence from public sources. Verify each fact independently.",
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
    if (item.retrieved_at) lines.push(`- Retrieved: ${formatRetrieved(item.retrieved_at)}`);
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

async function downloadDossier(data, button) {
  const original = button.textContent;
  button.disabled = true;
  button.textContent = "Building PDF…";
  try {
    const response = await fetch(`${API_BASE}/api/dossier`, {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ data }),
    });
    if (!response.ok) {
      let msg = `HTTP ${response.status}`;
      try {
        const err = await response.json();
        msg = err.message || msg;
      } catch (e) {}
      throw new Error(msg);
    }
    const blob = await response.blob();
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    const safe = String(data.query || "report").replace(/[^A-Za-z0-9._-]+/g, "_").slice(0, 60);
    link.download = `osint-dossier-${safe}.pdf`;
    link.click();
    URL.revokeObjectURL(link.href);
  } catch (err) {
    button.textContent = "PDF failed";
    setTimeout(() => (button.textContent = original), 2500);
    return;
  } finally {
    button.disabled = false;
    if (button.textContent === "Building PDF…") button.textContent = original;
  }
}

// fetch a file from the API and hand it to the browser as a download
async function downloadFile(url, options, filename, button) {
  const original = button.textContent;
  button.disabled = true;
  button.textContent = "Preparing…";
  try {
    const response = await fetch(url, { ...options, headers: authHeaders(options.headers || {}) });
    if (!response.ok) {
      let msg = `HTTP ${response.status}`;
      try {
        msg = (await response.json()).message || msg;
      } catch (e) {}
      throw new Error(msg);
    }
    const blob = await response.blob();
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = filename;
    link.click();
    URL.revokeObjectURL(link.href);
    button.textContent = original;
  } catch (err) {
    button.textContent = "failed — retry";
    button.title = err.message || "";
    setTimeout(() => (button.textContent = original), 3000);
  } finally {
    button.disabled = false;
  }
}

function safeFileName(value) {
  return String(value || "graph").replace(/[^A-Za-z0-9._-]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 60) || "graph";
}

// ROADMAP 7.8: GraphML for Gephi / yEd / Cytoscape, CSV for Maltego CE's table import
function buildGraphExport(getRequest, name) {
  const row = document.createElement("div");
  row.className = "chip-row";
  const label = document.createElement("span");
  label.textContent = "Export graph:";
  row.appendChild(label);
  [["GraphML", "graphml", "graphml"], ["Maltego CSV", "maltego", "csv"]].forEach(([text, fmt, ext]) => {
    const btn = buildActionButton(text, () =>
      downloadFile(...getRequest(fmt), `${safeFileName(name)}.${ext}`, btn));
    btn.title = fmt === "graphml" ? "Opens in Gephi, yEd or Cytoscape" : "Maltego CE: Import → Import Graph from Table";
    row.appendChild(btn);
  });
  return row;
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
  const tabByType = {
    username: "username",
    company: "company",
    domain: "domain",
    ip: "domain",
    email: "email",
    phone: "phone",
    name: "name",
  };
  const tab = tabByType[pivot.type] || "domain";
  activateTab(tab);
  const panel = getPanel(tab);
  panel.input.value = pivot.value;
  panel.form.requestSubmit();
}

const PIVOT_COLORS = {
  username: "var(--cyan)",
  domain: "var(--violet)",
  ip: "var(--pink)",
  company: "var(--mint)",
  email: "var(--amber, #f0b429)",
  phone: "var(--rose, #fb7185)",
  name: "var(--sky, #38bdf8)",
};
const GRAPH_MAX_NODES = 16;

function svgEl(tag, attrs) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, value] of Object.entries(attrs)) {
    el.setAttribute(key, value);
  }
  return el;
}

function buildGraph(data) {
  const pivots = (data.pivots || []).slice(0, GRAPH_MAX_NODES);
  const width = 760;
  const height = Math.max(320, 150 + pivots.length * 18);
  const cx = width / 2;
  const cy = height / 2;
  const radius = Math.min(cx, cy) - 90;

  const svg = svgEl("svg", {
    viewBox: `0 0 ${width} ${height}`,
    class: "graph-svg",
    role: "img",
  });

  // edges first (under nodes)
  const positions = pivots.map((pivot, index) => {
    const angle = (2 * Math.PI * index) / pivots.length - Math.PI / 2;
    return { x: cx + radius * Math.cos(angle), y: cy + radius * Math.sin(angle), pivot };
  });
  positions.forEach(({ x, y }) => {
    svg.appendChild(svgEl("line", {
      x1: cx, y1: cy, x2: x, y2: y, class: "graph-edge",
    }));
  });

  // center node
  const center = svgEl("g", { class: "graph-node graph-center" });
  center.appendChild(svgEl("circle", { cx, cy, r: 30 }));
  const centerText = svgEl("text", { x: cx, y: cy + 4, "text-anchor": "middle" });
  centerText.textContent =
    String(data.query).length > 16 ? String(data.query).slice(0, 15) + "…" : data.query;
  center.appendChild(centerText);
  svg.appendChild(center);

  // pivot nodes
  positions.forEach(({ x, y, pivot }) => {
    const g = svgEl("g", { class: "graph-node" });
    g.style.cursor = "pointer";
    const color = PIVOT_COLORS[pivot.type] || "var(--muted)";
    const circle = svgEl("circle", { cx: x, cy: y, r: 7, fill: color });
    g.appendChild(circle);
    const onRight = x >= cx;
    const label = svgEl("text", {
      x: x + (onRight ? 12 : -12),
      y: y + 4,
      "text-anchor": onRight ? "start" : "end",
      fill: color,
    });
    const value = String(pivot.value);
    label.textContent = value.length > 22 ? value.slice(0, 21) + "…" : value;
    g.appendChild(label);
    g.addEventListener("click", () => pivotTo(pivot));
    svg.appendChild(g);
  });

  const wrapper = document.createElement("div");
  wrapper.className = "graph-wrap hidden";
  wrapper.appendChild(svg);
  const legend = document.createElement("div");
  legend.className = "graph-legend";
  legend.innerHTML = Object.entries(PIVOT_COLORS)
    .map(([type, color]) => `<span style="color:${color}">● ${type}</span>`)
    .join(" ");
  wrapper.appendChild(legend);
  return wrapper;
}

function buildToolbar(data) {
  const toolbar = document.createElement("div");
  toolbar.className = "toolbar";
  if (data.results.length) {
    const exports = document.createElement("div");
    exports.className = "chip-row";
    exports.appendChild(buildActionButton("Export MD", () => downloadReport(data, "md")));
    exports.appendChild(buildActionButton("Export JSON", () => downloadReport(data, "json")));
    exports.appendChild(buildActionButton("Print", () => window.print()));
    const dossierBtn = buildActionButton("PDF Dossier", () =>
      downloadDossier(data, dossierBtn)
    );
    exports.appendChild(dossierBtn);
    exports.appendChild(buildActionButton("Save to case", () => saveToCase(data)));
    const aiBox = document.createElement("div");
    aiBox.className = "ai-summary hidden";
    const aiButton = buildActionButton("AI Summary", () => analyzeWithAI(data, aiBox, aiButton));
    exports.appendChild(aiButton);
    if (data.preview_b64) {
      const visionButton = buildActionButton("AI Vision", () =>
        analyzeVision(data, aiBox, visionButton)
      );
      exports.appendChild(visionButton);
    }
    toolbar.appendChild(exports);
    toolbar.appendChild(aiBox);
  }
  if (Array.isArray(data.pivots) && data.pivots.length) {
    const graph = buildGraph(data);
    const toggle = buildActionButton("Graph", () => {
      graph.classList.toggle("hidden");
    });
    const graphRow = document.createElement("div");
    graphRow.className = "chip-row";
    graphRow.appendChild(toggle);
    toolbar.appendChild(graphRow);
    toolbar.appendChild(graph);

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
    links.className = "chip-row manual-links";
    const label = document.createElement("span");
    label.textContent =
      "NOT checked by the tool. These only open each service so you can look yourself:";
    links.appendChild(label);
    data.links.forEach((item) => {
      const link = document.createElement("a");
      link.className = "chip";
      link.href = item.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = `${item.label} ↗`;
      link.title = "Opens the service. Nothing was verified.";
      links.appendChild(link);
    });
    toolbar.appendChild(links);
  }
  if (Array.isArray(data.username_ideas) && data.username_ideas.length) {
    const ideas = document.createElement("div");
    ideas.className = "chip-row manual-links";
    const label = document.createElement("span");
    label.textContent =
      "Guessed from the name, NOT found anywhere. Click one to check it as a username:";
    ideas.appendChild(label);
    data.username_ideas.forEach((handle) => {
      const btn = buildActionButton(handle, () => pivotTo({ type: "username", value: handle }));
      btn.title = "A guess built from the name. Running it checks whether such accounts exist.";
      ideas.appendChild(btn);
    });
    toolbar.appendChild(ideas);
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

  if (data.message) {
    // e.g. phone: only numbering-plan info, nothing found online
    const msg = document.createElement("div");
    msg.className = "empty-state";
    msg.textContent = data.message;
    panel.results.appendChild(msg);
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
    let message = data.message || data.detail || data.error || `Request failed with HTTP ${response.status}.`;
    if (response.status === 401) message += " Enter the key in the Data tab.";
    const error = new Error(message);
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

const DEEP_NODE_TYPE_TAB = {
  username: "username",
  email: "email",
  name: "name",
  phone: "phone",
  domain: "domain",
  ip: "domain",
  company: "company",
};

function deepScanToFlat(data) {
  // Flatten a deep-scan graph into the normal {results, pivots} shape so the
  // existing toolbar (export / AI summary / save-to-case) works unchanged.
  const results = [];
  (data.nodes || []).forEach((node) => {
    (node.results || []).forEach((item) => {
      const clone = Object.assign({}, item);
      clone.info = `via ${node.type} "${node.query}"` +
        (clone.info ? " — " + clone.info : "");
      results.push(clone);
    });
  });
  return {
    status: "success",
    category: "deep_scan",
    query: data.query,
    results,
    count: results.length,
    pivots: [],
    warnings: data.warnings,
    notice: data.notice,
    // carry the graph so the PDF dossier keeps nodes, edges and clusters
    seed_type: data.seed_type,
    nodes: data.nodes,
    edges: data.edges,
    clusters: data.clusters,
  };
}

function buildDeepGraph(data) {
  const nodes = data.nodes || [];
  if (!nodes.length) return null;

  const byDepth = {};
  nodes.forEach((n) => {
    (byDepth[n.depth] = byDepth[n.depth] || []).push(n);
  });
  const depths = Object.keys(byDepth).map(Number).sort((a, b) => a - b);

  const colW = 230;
  const rowH = 64;
  const padX = 24;
  const padY = 40;
  const maxRows = Math.max(...depths.map((d) => byDepth[d].length));
  const width = padX * 2 + (depths.length - 1) * colW + 170;
  const height = Math.max(240, padY * 2 + (maxRows - 1) * rowH + 40);

  const svg = svgEl("svg", {
    viewBox: `0 0 ${width} ${height}`,
    class: "graph-svg deep-graph",
    role: "img",
  });

  const pos = {};
  depths.forEach((d, di) => {
    const col = byDepth[d];
    const colH = (col.length - 1) * rowH;
    const startY = (height - colH) / 2;
    col.forEach((n, ni) => {
      pos[n.key] = { x: padX + di * colW + 30, y: startY + ni * rowH, node: n };
    });
  });

  // edges first
  (data.edges || []).forEach((e) => {
    const a = pos[e.from];
    const b = pos[e.to];
    if (!a || !b) return;
    const path = svgEl("path", {
      d: `M ${a.x} ${a.y} C ${a.x + colW / 2} ${a.y}, ${b.x - colW / 2} ${b.y}, ${b.x} ${b.y}`,
      class: "graph-edge",
      fill: "none",
    });
    svg.appendChild(path);
  });

  // nodes
  Object.values(pos).forEach(({ x, y, node }) => {
    const color = PIVOT_COLORS[node.type] || "var(--muted)";
    const g = svgEl("g", { class: "graph-node" });
    g.style.cursor = "pointer";
    g.appendChild(svgEl("circle", { cx: x, cy: y, r: node.depth === 0 ? 9 : 6, fill: color }));
    const label = svgEl("text", { x: x + 12, y: y + 4, "text-anchor": "start", fill: color });
    const v = String(node.query);
    label.textContent = (v.length > 20 ? v.slice(0, 19) + "…" : v) +
      (node.count ? ` (${node.count})` : "");
    g.appendChild(label);
    g.addEventListener("click", () => pivotTo({ type: node.type, value: node.query }));
    svg.appendChild(g);
  });

  const wrapper = document.createElement("div");
  wrapper.className = "graph-wrap deep-graph-wrap";
  wrapper.appendChild(svg);
  const legend = document.createElement("div");
  legend.className = "graph-legend";
  const usedTypes = [...new Set(nodes.map((n) => n.type))];
  legend.innerHTML = usedTypes
    .map((t) => `<span style="color:${PIVOT_COLORS[t] || "var(--muted)"}">● ${t}</span>`)
    .join(" ");
  wrapper.appendChild(legend);
  return wrapper;
}

function buildClusters(data) {
  // multi-node identities, plus single nodes that have namesake candidates
  const clusters = (data.clusters || []).filter(
    (c) => (c.members || []).length > 1 || (c.candidates || []).length
  );
  if (!clusters.length) return null;

  const wrap = document.createElement("div");
  const head = document.createElement("div");
  head.className = "section-head";
  head.textContent = `Identity clusters (${clusters.length})`;
  wrap.appendChild(head);

  clusters.forEach((c) => {
    const card = document.createElement("div");
    card.className = "card cluster-card";

    const top = document.createElement("div");
    top.className = "card-head";
    const title = document.createElement("h3");
    title.className = "card-title";
    title.textContent = c.label || "entity";
    top.appendChild(title);
    const badge = document.createElement("span");
    badge.className = `badge conf-${c.confidence}`;
    badge.textContent = `${c.confidence} · ${c.members.length} nodes`;
    top.appendChild(badge);
    card.appendChild(top);

    const idLine = [];
    const ids = c.identifiers || {};
    if (ids.names && ids.names.length) idLine.push("names: " + ids.names.join(", "));
    if (ids.emails && ids.emails.length) idLine.push("emails: " + ids.emails.join(", "));
    if (ids.usernames && ids.usernames.length)
      idLine.push("handles: " + ids.usernames.map((u) => "@" + u).join(", "));
    if (ids.domains && ids.domains.length) idLine.push("domains: " + ids.domains.join(", "));
    if (idLine.length) {
      const meta = document.createElement("div");
      meta.className = "card-meta";
      meta.innerHTML = idLine.map((l) => escapeHtml(l)).join("<br />");
      card.appendChild(meta);
    }

    if (c.signals && c.signals.length) {
      const sig = document.createElement("div");
      sig.className = "cluster-signals";
      sig.innerHTML =
        "why linked: " +
        c.signals.map((s) => `<span class="tag">${escapeHtml(s)}</span>`).join(" ");
      card.appendChild(sig);
    }

    if (c.contradictions && c.contradictions.length) {
      c.contradictions.forEach((x) => {
        const warn = document.createElement("div");
        warn.className = "cluster-contradiction";
        warn.textContent = "⚠ " + x;
        card.appendChild(warn);
      });
    }

    if (c.platforms && c.platforms.length) {
      const plat = document.createElement("div");
      plat.className = "card-meta";
      plat.textContent = "seen on: " + c.platforms.join(", ");
      card.appendChild(plat);
    }

    if (c.candidates && c.candidates.length) {
      // NOT merged: same display name only. Verify before treating as this person.
      const cand = document.createElement("div");
      cand.className = "cluster-candidates";
      const label = document.createElement("div");
      label.textContent =
        `Unconfirmed candidates (${c.candidates.length}) — may be different people:`;
      cand.appendChild(label);
      c.candidates.forEach((x) => {
        const row = document.createElement("div");
        row.className = "card-meta";
        row.textContent = `@${x.query} — ${x.reason}`;
        cand.appendChild(row);
        if (x.ai_review) {
          // local model's cited opinion: a weak signal, the human decides
          const ai = document.createElement("div");
          ai.className = `card-meta ai-review ai-${x.ai_review.verdict}`;
          const verdict = { same: "looks like the same person", different: "looks like a different person",
                            unclear: "unclear" }[x.ai_review.verdict] || x.ai_review.verdict;
          ai.textContent = `   AI (${x.ai_review.model}, weak signal): ${verdict} — ${x.ai_review.reason}` +
            (x.ai_review.evidence_ids.length ? ` [${x.ai_review.evidence_ids.join(", ")}]` : "");
          cand.appendChild(ai);
        }
      });
      card.appendChild(cand);
    }

    wrap.appendChild(card);
  });
  return wrap;
}

function renderDeepScan(panel, data) {
  const nodes = data.nodes || [];
  panel.summary.innerHTML =
    `<strong>${data.node_count}</strong> node${data.node_count === 1 ? "" : "s"} ` +
    `mapped from ${escapeHtml(`"${data.query}"`)} ` +
    `<span class="tag">${escapeHtml(data.seed_type)}</span>` +
    (data.truncated ? ' <span class="tag">truncated at scan limit</span>' : "");

  // toolbar (export / AI / save) via flattened view
  panel.results.appendChild(buildToolbar(deepScanToFlat(data)));
  const scanBody = { nodes: data.nodes || [], edges: data.edges || [], clusters: data.clusters || [],
                     query: data.query, seed_type: data.seed_type };
  panel.results.appendChild(buildGraphExport((fmt) => [`${API_BASE}/api/export/graph`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scan: scanBody, format: fmt }),
  }], `deep-scan-${data.query}`));

  const clusters = buildClusters(data);
  if (clusters) panel.results.appendChild(clusters);

  const graph = buildDeepGraph(data);
  if (graph) {
    graph.classList.remove("hidden");
    panel.results.appendChild(graph);
  }

  if (Array.isArray(data.warnings) && data.warnings.length) {
    const warnings = document.createElement("div");
    warnings.className = "warnings";
    const head = document.createElement("div");
    head.className = "warnings-head";
    head.textContent = `${data.warnings.length} note${data.warnings.length === 1 ? "" : "s"} (skipped or unavailable)`;
    warnings.appendChild(head);
    data.warnings.forEach((w) => {
      const item = document.createElement("div");
      item.className = "warning-item";
      item.textContent = w;
      warnings.appendChild(item);
    });
    panel.results.appendChild(warnings);
  }

  if (!nodes.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "No public traces found from this seed.";
    panel.results.appendChild(empty);
    return;
  }

  nodes.forEach((node) => {
    const header = document.createElement("div");
    header.className = "section-head deep-node-head";
    const tab = DEEP_NODE_TYPE_TAB[node.type] || "domain";
    header.innerHTML =
      `<span class="tag" style="color:${PIVOT_COLORS[node.type] || "var(--muted)"}">${escapeHtml(node.type)}</span> ` +
      `${escapeHtml(node.query)} · depth ${node.depth} · ${node.count} result${node.count === 1 ? "" : "s"}`;
    const open = buildActionButton("Open in " + tab, () =>
      pivotTo({ type: node.type, value: node.query })
    );
    open.classList.add("chip-sm");
    header.appendChild(open);
    panel.results.appendChild(header);

    if (!node.results || !node.results.length) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.textContent = node.message || "No results for this node.";
      panel.results.appendChild(empty);
      return;
    }
    node.results.slice(0, 20).forEach((item, index) => {
      const card = buildCard(item);
      card.style.animationDelay = `${Math.min(index * 30, 300)}ms`;
      panel.results.appendChild(card);
    });
  });
}

async function handleDeepScan(event) {
  event.preventDefault();
  const panel = getPanel("deepscan");
  const query = panel.input.value.trim();
  const type = document.getElementById("deep-scan-type").value;

  clearPanel(panel);
  if (!query) {
    showError(panel, "Please enter a seed before scanning.");
    return;
  }
  if (panel.controller) panel.controller.abort();
  panel.controller = new AbortController();
  const signal = panel.controller.signal;

  setLoading(panel, true);
  try {
    const data = await requestJson(`${API_BASE}/api/deep-scan`, {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ query, type: type || null }),
      signal,
    });
    if (!data || data.status !== "success") {
      showError(panel, (data && (data.message || data.detail)) || "Deep scan failed.");
      return;
    }
    renderDeepScan(panel, data);
  } catch (err) {
    if (err.name === "AbortError") return;
    showError(
      panel,
      err.message ||
        `Could not reach the backend at ${API_BASE}. Make sure it is running.`
    );
  } finally {
    setLoading(panel, false);
  }
}

// ---- Agent mode (Faza 6): free text -> live steps -> sourced candidates ----

const AGENT_POLL_MS = 1500;
const AGENT_MAX_POLLS = 900; // ~22 minutes, the worker's job limit
const AGENT_FIELDS = [
  ["name", "Name"],
  ["birth_year", "Birth year"],
  ["location", "Location"],
  ["work", "Work / study"],
  ["emails", "E-mail"],
  ["usernames", "Username"],
  ["profiles", "Profiles"],
];
const AGENT_STEP_ICON = { parse: "◆", plan: "▸", check: "✓", skip: "↷", link: "⛓", rank: "⚖", error: "⚠" };
const AGENT_LEVEL_TEXT = { strong: "strong lead", possible: "possible", weak: "weak" };
let agentRun = null; // { id, decisions }

function safeHttpUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
  } catch (e) {
    return null;
  }
}

function agentAddSteps(list, steps) {
  steps.forEach((step) => {
    const li = document.createElement("li");
    li.className = `agent-step step-${step.kind}`;
    const icon = document.createElement("span");
    icon.className = "agent-step-icon";
    icon.textContent = AGENT_STEP_ICON[step.kind] || "•";
    const text = document.createElement("span");
    text.textContent = step.text;
    li.append(icon, text);
    list.appendChild(li);
  });
  list.classList.toggle("hidden", !list.children.length);
}

function agentSourceLinks(sources) {
  const wrap = document.createElement("span");
  wrap.className = "agent-sources";
  (sources || []).forEach((src) => {
    const url = safeHttpUrl(src.url);
    const el = document.createElement(url ? "a" : "span");
    el.className = "agent-source";
    el.textContent = src.platform || "source";
    if (url) {
      el.href = url;
      el.target = "_blank";
      el.rel = "noopener noreferrer";
      el.title = url + (src.retrieved_at ? ` — retrieved ${formatRetrieved(src.retrieved_at)}` : "");
    }
    wrap.appendChild(el);
  });
  return wrap;
}

function agentFieldRows(candidate) {
  const table = document.createElement("div");
  table.className = "agent-fields";
  AGENT_FIELDS.forEach(([key, label]) => {
    const name = document.createElement("div");
    name.className = "agent-field-name";
    name.textContent = label;
    const values = document.createElement("div");
    values.className = "agent-field-values" + (key === "profiles" ? " agent-profiles" : "");
    const items = (candidate.fields || {})[key] || [];
    if (!items.length) {
      values.classList.add("agent-missing");
      values.textContent = "not found";
    }
    items.forEach((item) => {
      const row = document.createElement("div");
      row.className = "agent-value";
      if (key !== "profiles") {
        const v = document.createElement("span");
        v.textContent = item.value;
        row.appendChild(v);
      }
      row.appendChild(agentSourceLinks(item.sources));
      values.appendChild(row);
    });
    table.append(name, values);
  });
  return table;
}

function agentDecisionBadge(decision) {
  const badge = document.createElement("span");
  badge.className = `badge decision-${decision || "none"}`;
  badge.textContent = decision === "confirmed" ? "confirmed by you" : decision === "rejected" ? "rejected by you" : "needs your decision";
  return badge;
}

async function agentDecide(candidateId, decision, card) {
  const data = await requestJson(`${API_BASE}/api/agent/${agentRun.id}/decision`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ candidate_id: candidateId, decision }),
  });
  const value = data.decision.decision === "undecided" ? null : data.decision.decision;
  card.classList.remove("decided-confirmed", "decided-rejected");
  if (value) card.classList.add(`decided-${value}`);
  card.querySelector(".badge[class*='decision-']").replaceWith(agentDecisionBadge(value));
}

// 10.1: same username on another site, but the profile describes someone else
function buildAgentSetAside(items) {
  const box = document.createElement("details");
  box.className = "agent-set-aside";
  const summary = document.createElement("summary");
  summary.textContent = `Same username, probably another person (${items.length}) — not used`;
  box.appendChild(summary);
  const list = document.createElement("ul");
  items.forEach((item) => {
    const li = document.createElement("li");
    const url = safeHttpUrl(item.url);
    const name = document.createElement(url ? "a" : "span");
    name.textContent = item.platform || "profile";
    if (url) {
      name.href = url;
      name.target = "_blank";
      name.rel = "noopener noreferrer";
    }
    li.append(name, ` — ${item.reason}`);
    list.appendChild(li);
  });
  box.appendChild(list);
  return box;
}

function buildAgentCandidate(c, decision) {
  const card = document.createElement("div");
  card.className = `card agent-card level-${c.level}` + (decision ? ` decided-${decision}` : "");

  const head = document.createElement("div");
  head.className = "card-head";
  const title = document.createElement("h3");
  title.className = "card-title";
  title.textContent = c.label;
  const level = document.createElement("span");
  level.className = `badge lead-${c.level}`;
  level.textContent = `${AGENT_LEVEL_TEXT[c.level] || c.level} · ${c.score}`;
  head.append(title, level, agentDecisionBadge(decision));
  card.appendChild(head);

  card.appendChild(agentFieldRows(c));

  if (c.why && c.why.length) {
    const why = document.createElement("ul");
    why.className = "agent-why";
    c.why.forEach((w) => {
      const li = document.createElement("li");
      li.textContent = w;
      why.appendChild(li);
    });
    card.appendChild(why);
  }
  (c.contradictions || []).forEach((x) => {
    const warn = document.createElement("div");
    warn.className = "cluster-contradiction";
    warn.textContent = "⚠ " + x;
    card.appendChild(warn);
  });
  if (c.ai_review) {
    const ai = document.createElement("div");
    ai.className = `card-meta ai-review ai-${c.ai_review.verdict}`;
    ai.textContent = `AI (${c.ai_review.model}, weak signal): ${c.ai_review.verdict} — ${c.ai_review.reason}`;
    card.appendChild(ai);
  }

  // 10.2: a source that did not answer is "not checked", not "nothing there"
  if ((c.unchecked || []).length) {
    const note = document.createElement("div");
    note.className = "agent-unchecked";
    note.textContent = `Not checked this time: ${c.unchecked.join(", ")} — the score may be lower than it should be. Run again later.`;
    card.appendChild(note);
  }

  card.appendChild(buildAgentContacts(c.contacts || []));
  if ((c.chain || []).length) card.appendChild(buildAgentChain(c.chain));
  if ((c.set_aside || []).length) card.appendChild(buildAgentSetAside(c.set_aside));

  const members = document.createElement("div");
  members.className = "card-meta";
  members.textContent = "records: " + (c.members || []).map((m) =>
    `${m.type} ${m.query}${m.via ? ` (${m.via})` : ""}${m.not_followed ? " — not followed further" : ""}`
  ).join(" · ");
  card.appendChild(members);

  // ROADMAP 6.6: the final call is the human's
  const actions = document.createElement("div");
  actions.className = "chip-row agent-actions";
  [["Confirm", "confirmed"], ["Reject", "rejected"], ["Undo", "undecided"]].forEach(([label, value]) => {
    const btn = buildActionButton(label, async () => {
      btn.disabled = true;
      try {
        await agentDecide(c.id, value, card);
      } catch (err) {
        btn.textContent = "failed — retry";
      } finally {
        btn.disabled = false;
      }
    });
    if (value === "rejected") btn.classList.add("chip-danger");
    actions.appendChild(btn);
  });
  // ROADMAP 7.1: the person card as a PDF (carries your decision)
  const runId = agentRun && agentRun.id;
  const pdfBtn = buildActionButton("Person card (PDF)", () =>
    downloadFile(`${API_BASE}/api/agent/${runId}/card/${c.id}/pdf`, {},
                 `person-card-${safeFileName(c.label)}.pdf`, pdfBtn));
  actions.appendChild(pdfBtn);
  card.appendChild(actions);
  return card;
}

const CONTACT_KIND_TEXT = { email: "E-mail", phone: "Phone", messenger: "Messenger", social: "Profile", website: "Website" };

// ROADMAP 7.2: contacts the person published, each with the page it was read on
function buildContactRows(contacts) {
  const list = document.createElement("div");
  list.className = "agent-contacts";
  contacts.forEach((item) => {
    const row = document.createElement("div");
    row.className = "agent-value";
    const kind = document.createElement("span");
    kind.className = "tag";
    kind.textContent = CONTACT_KIND_TEXT[item.kind] || item.kind;
    const value = document.createElement("span");
    value.textContent = ` ${item.value} `;
    const how = document.createElement("span");
    how.className = "card-meta";
    how.textContent = item.how ? `— ${item.how} ` : "";
    // label each page by its path ("/contact"), so several sources are told apart
    const pageLabel = (u) => {
      try {
        const url = new URL(u);
        return url.pathname === "/" ? url.hostname : url.pathname.slice(0, 40);
      } catch (e) {
        return "page";
      }
    };
    row.append(kind, value, how,
               agentSourceLinks((item.sources || []).map((u) => ({ platform: pageLabel(u), url: u }))));
    list.appendChild(row);
  });
  return list;
}

function buildAgentContacts(contacts) {
  const box = document.createElement("div");
  box.className = "agent-contact-box";
  const head = document.createElement("div");
  head.className = "agent-field-name";
  head.textContent = "Published contacts";
  box.appendChild(head);
  if (!contacts.length) {
    const none = document.createElement("div");
    none.className = "agent-missing";
    none.textContent = "none published on the pages read";
    box.appendChild(none);
    return box;
  }
  box.appendChild(buildContactRows(contacts));
  return box;
}

function buildAgentChain(chain) {
  const details = document.createElement("details");
  details.className = "agent-chain";
  const sum = document.createElement("summary");
  sum.textContent = "Evidence chain: how each record was reached";
  details.appendChild(sum);
  const list = document.createElement("ol");
  chain.forEach((link) => {
    const li = document.createElement("li");
    li.textContent = (link.path || []).map((s) => `${s.type} “${s.value}” (${s.via})`).join(" → ") || link.record;
    list.appendChild(li);
  });
  details.appendChild(list);
  return details;
}

function renderAgent(panel, run) {
  const result = run.result || {};
  const candidates = result.candidates || [];
  const strong = candidates.filter((c) => c.level === "strong").length;
  panel.summary.innerHTML =
    `<strong>${candidates.length}</strong> candidate${candidates.length === 1 ? "" : "s"}, ` +
    `<strong>${strong}</strong> strong · ${result.node_count || 0} records checked` +
    (result.truncated ? ' <span class="tag">stopped at scan limit</span>' : "");

  const notice = document.createElement("div");
  notice.className = "agent-notice";
  notice.textContent = result.notice || "";
  panel.results.appendChild(notice);

  if (!candidates.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "No candidate profiles found. Add a username, e-mail or a different spelling and try again.";
    panel.results.appendChild(empty);
  }
  candidates.forEach((c) => {
    const decision = (run.decisions || {})[c.id];
    panel.results.appendChild(buildAgentCandidate(c, decision && decision.decision));
  });

  const official = (result.overview || {}).name_search || [];
  if (official.length) {
    const box = document.createElement("div");
    box.className = "card agent-overview";
    const h = document.createElement("h3");
    h.className = "card-title";
    h.textContent = "Name search: registers and knowledge bases";
    box.appendChild(h);
    official.forEach((item) => {
      const row = document.createElement("div");
      row.className = "card-meta";
      row.appendChild(agentSourceLinks([{ platform: item.platform, url: item.url }]));
      row.append(" " + (item.info || ""));
      box.appendChild(row);
    });
    panel.results.appendChild(box);
  }

  if (result.scan && (result.scan.nodes || []).length) {
    panel.results.appendChild(buildGraphExport((fmt) =>
      [`${API_BASE}/api/agent/${run.id}/graph?format=${fmt}`, {}], `agent-${result.query}`));
    const details = document.createElement("details");
    details.className = "agent-details";
    const sum = document.createElement("summary");
    sum.textContent = `All checked records and the link graph (${result.scan.nodes.length})`;
    details.appendChild(sum);
    const inner = { summary: document.createElement("div"), results: document.createElement("div") };
    inner.results.className = "results";
    details.append(inner.summary, inner.results);
    let drawn = false;
    details.addEventListener("toggle", () => {
      if (details.open && !drawn) {
        drawn = true;
        renderDeepScan(inner, { ...result.scan, node_count: result.scan.nodes.length,
                                query: result.query, truncated: result.truncated });
      }
    });
    panel.results.appendChild(details);
  }
}

async function handleAgent(event) {
  event.preventDefault();
  const panel = getPanel("agent");
  const steps = panel.root.querySelector(".agent-steps");
  // ROADMAP 7.6: the optional fields become plain phrases the parser reads,
  // so the "Understood:" step shows exactly what was used
  const form = panel.form;
  const extra = [];
  const field = (name) => (form.elements[name] ? form.elements[name].value.trim() : "");
  if (field("city")) extra.push(`from ${field("city")}`);
  if (field("age")) extra.push(`${field("age")} years old`);
  if (field("work")) extra.push(`works at ${field("work")}`);
  if (field("school")) extra.push(`studies at ${field("school")}`);
  const text = [panel.input.value.trim(), ...extra].join(", ").slice(0, 500);
  clearPanel(panel);
  steps.innerHTML = "";
  steps.classList.add("hidden");
  if (!text) {
    showError(panel, "Describe the person first.");
    return;
  }
  if (panel.controller) panel.controller.abort();
  panel.controller = new AbortController();
  const signal = panel.controller.signal;
  setLoading(panel, true);
  try {
    const started = await requestJson(`${API_BASE}/api/agent`, {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ text }),
      signal,
    });
    agentRun = { id: started.run_id };
    let seen = 0;
    for (let i = 0; i < AGENT_MAX_POLLS; i++) {
      const data = await requestJson(`${API_BASE}/api/agent/${started.run_id}?after=${seen}`, {
        headers: authHeaders(),
        signal,
      });
      const run = data.run;
      agentAddSteps(steps, run.steps || []);
      if ((run.steps || []).length) seen = run.steps[run.steps.length - 1].seq;
      if (run.status === "complete") {
        renderAgent(panel, run);
        return;
      }
      if (run.status === "failed") {
        showError(panel, run.error || "The agent run failed.");
        return;
      }
      await sleep(AGENT_POLL_MS, signal);
    }
    showError(panel, "The agent is taking too long. Check again later.");
  } catch (err) {
    if (err.name === "AbortError") return;
    showError(panel, err.message || `Could not reach the backend at ${API_BASE}.`);
  } finally {
    setLoading(panel, false);
  }
}

// ROADMAP 7.7: read the contacts a page publishes
async function handleContacts(event) {
  event.preventDefault();
  const panel = getPanel("contacts");
  const url = panel.input.value.trim();
  clearPanel(panel);
  if (!url) {
    showError(panel, "Give the page URL.");
    return;
  }
  if (panel.controller) panel.controller.abort();
  panel.controller = new AbortController();
  setLoading(panel, true);
  try {
    const data = await requestJson(`${API_BASE}/api/contacts`, {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ url }),
      signal: panel.controller.signal,
    });
    const contacts = data.contacts || [];
    panel.summary.innerHTML =
      `<strong>${contacts.length}</strong> contact${contacts.length === 1 ? "" : "s"} on ` +
      `<strong>${(data.pages || []).length}</strong> page${(data.pages || []).length === 1 ? "" : "s"} read`;
    const notice = document.createElement("div");
    notice.className = "notice";
    notice.textContent = data.notice || "";
    panel.results.appendChild(notice);
    if (contacts.length) {
      const card = document.createElement("div");
      card.className = "card contacts-card";
      card.appendChild(buildContactRows(contacts));
      panel.results.appendChild(card);
    } else {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.textContent = "No e-mail, phone or profile link is published on the pages read.";
      panel.results.appendChild(empty);
    }
    if ((data.notes || []).length) {
      const warnings = document.createElement("div");
      warnings.className = "warnings";
      data.notes.forEach((w) => {
        const item = document.createElement("div");
        item.className = "warning-item";
        item.textContent = w;
        warnings.appendChild(item);
      });
      panel.results.appendChild(warnings);
    }
  } catch (err) {
    if (err.name === "AbortError") return;
    showError(panel, err.message || `Could not reach the backend at ${API_BASE}.`);
  } finally {
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
      checkSources();
      return;
    }
    throw new Error("unhealthy");
  } catch (err) {
    el.textContent = "[API OFFLINE]";
    el.classList.add("offline");
    el.classList.remove("online");
  }
}

// Source health: one compact badge, details in its tooltip.
async function checkSources() {
  const el = document.getElementById("sources-status");
  if (!el) return;
  try {
    const data = await requestJson(`${API_BASE}/api/sources/health`, { headers: authHeaders() });
    const entries = Object.entries(data.sources || {});
    const bad = entries.filter(([, s]) => !s.ok);
    el.textContent = bad.length
      ? `[SOURCES ${entries.length - bad.length}/${entries.length} OK]`
      : "[SOURCES OK]";
    el.classList.toggle("online", !bad.length);
    el.classList.toggle("offline", bad.length > 0);
    const keys = Object.entries(data.keys || {})
      .map(([k, on]) => `${k}: ${on ? "set" : "not set"}`)
      .join("\n");
    el.title =
      entries.map(([name, s]) => `${s.ok ? "OK" : "!!"} ${name}: ${s.detail}`).join("\n") +
      "\n\nOptional keys (paid ones are not needed; free sources cover them):\n" + keys;
  } catch (err) {
    el.textContent = "";
  }
}

document.querySelectorAll(".tab[data-tab]").forEach((btn) => {
  btn.addEventListener("click", () => activateTab(btn.dataset.tab));
});

document.querySelectorAll(
  ".search-form:not(#deep-scan-form):not(#watch-form):not(#agent-form):not(#contacts-form)"
).forEach((form) => {
  form.addEventListener("submit", handleSubmit);
});

document.getElementById("deep-scan-form").addEventListener("submit", handleDeepScan);
document.getElementById("agent-form").addEventListener("submit", handleAgent);
document.getElementById("contacts-form").addEventListener("submit", handleContacts);
document.getElementById("watch-form").addEventListener("submit", handleCreateWatch);

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
loadAiDefaults();

const caseNewBtn = document.getElementById("case-new-btn");
if (caseNewBtn) {
  const createFromInput = async () => {
    const input = document.getElementById("case-new-name");
    const name = input.value.trim();
    if (!name) return;
    try {
      const created = await caseApi("", { method: "POST", body: JSON.stringify({ name }) });
      setActiveCase(created.id);
      input.value = "";
      loadCases();
    } catch (err) {
      alert("Could not create case: " + err.message);
    }
  };
  caseNewBtn.addEventListener("click", createFromInput);
  document.getElementById("case-new-name").addEventListener("keydown", (e) => {
    if (e.key === "Enter") createFromInput();
  });
}


// ============================================================
//  Cases — group findings from many searches into one investigation
// ============================================================
const ACTIVE_CASE_KEY = "osint_active_case";

function activeCaseId() {
  try {
    return localStorage.getItem(ACTIVE_CASE_KEY) || "";
  } catch (err) {
    return "";
  }
}
function setActiveCase(id) {
  try {
    if (id) localStorage.setItem(ACTIVE_CASE_KEY, id);
    else localStorage.removeItem(ACTIVE_CASE_KEY);
  } catch (err) {
    /* ignore */
  }
}

async function caseApi(path, options = {}) {
  return requestJson(`${API_BASE}/api/cases${path}`, {
    ...options,
    headers: authHeaders({ "Content-Type": "application/json", ...(options.headers || {}) }),
  });
}

async function saveToCase(data) {
  let id = activeCaseId();
  try {
    if (!id) {
      const name = prompt("New case name:", `${data.category || "case"} - ${data.query}`);
      if (!name) return;
      const created = await caseApi("", { method: "POST", body: JSON.stringify({ name }) });
      id = created.id;
      setActiveCase(id);
    }
    await caseApi(`/${id}/findings`, {
      method: "POST",
      body: JSON.stringify({
        category: data.category || "search",
        query: String(data.query),
        result: data,
      }),
    });
    alert("Saved to case.");
  } catch (err) {
    alert("Could not save to case: " + err.message);
  }
}

function aggregateCase(detail) {
  const results = [];
  const pivots = [];
  const seen = new Set();
  detail.findings.forEach((f) => {
    (f.result.results || []).forEach((r) => results.push(r));
    (f.result.posts || []).forEach((r) => results.push(r));
    (f.result.pivots || []).forEach((p) => {
      const key = `${p.type}:${String(p.value).toLowerCase()}`;
      if (!seen.has(key)) {
        seen.add(key);
        pivots.push(p);
      }
    });
  });
  return {
    query: detail.case.name,
    category: "case",
    results,
    pivots,
    notice: "Combined case report aggregating every saved search.",
  };
}

async function loadCases() {
  const listEl = document.getElementById("case-list");
  const summaryEl = document.getElementById("case-summary");
  const resultsEl = document.getElementById("case-results");
  listEl.innerHTML = "";
  summaryEl.innerHTML = "";
  resultsEl.innerHTML = "";
  let cases;
  try {
    cases = (await caseApi("", { method: "GET" })).cases;
  } catch (err) {
    summaryEl.textContent = "Could not load cases: " + err.message;
    return;
  }
  if (!cases.length) {
    resultsEl.innerHTML =
      '<div class="empty-state">No cases yet. Create one, then use "Save to case" on any result.</div>';
    return;
  }
  const active = activeCaseId();
  cases.forEach((c) => {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "chip" + (c.id === active ? " chip-active" : "");
    chip.textContent = `${c.name} (${c.findings})`;
    chip.addEventListener("click", () => {
      setActiveCase(c.id);
      openCase(c.id);
      loadCases();
    });
    listEl.appendChild(chip);
  });
  const current = active && cases.some((c) => c.id === active) ? active : cases[0].id;
  setActiveCase(current);
  openCase(current);
}

async function openCase(caseId) {
  const summaryEl = document.getElementById("case-summary");
  const resultsEl = document.getElementById("case-results");
  resultsEl.innerHTML = "";
  let detail;
  try {
    detail = await caseApi(`/${caseId}`, { method: "GET" });
  } catch (err) {
    summaryEl.textContent = "Could not open case: " + err.message;
    return;
  }
  const n = detail.findings.length;
  summaryEl.innerHTML = `<strong>${escapeHtml(detail.case.name)}</strong> — ${n} finding${
    n === 1 ? "" : "s"
  }`;

  const combined = aggregateCase(detail);
  const toolbar = buildToolbar(combined);
  const del = buildActionButton("Delete case", async () => {
    if (!confirm(`Delete case "${detail.case.name}"?`)) return;
    await caseApi(`/${caseId}`, { method: "DELETE" });
    setActiveCase("");
    loadCases();
  });
  del.classList.add("chip-danger");
  const delRow = document.createElement("div");
  delRow.className = "chip-row";
  delRow.appendChild(del);
  toolbar.appendChild(delRow);
  resultsEl.appendChild(toolbar);

  if (!n) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = 'This case is empty. Use "Save to case" on a search result.';
    resultsEl.appendChild(empty);
    return;
  }

  detail.findings.forEach((f) => {
    const head = document.createElement("div");
    head.className = "section-head case-finding-head";
    const when = (f.created_at || "").replace("T", " ").replace("+00:00", " UTC");
    head.textContent = `${f.category}: ${f.query} — ${when}`;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "chip chip-danger case-remove";
    remove.textContent = "remove";
    remove.addEventListener("click", async () => {
      await caseApi(`/${caseId}/findings/${f.id}`, { method: "DELETE" });
      openCase(caseId);
    });
    head.appendChild(remove);
    resultsEl.appendChild(head);
    const items = [...(f.result.results || []), ...(f.result.posts || [])];
    if (!items.length) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.textContent = f.result.message || "No results in this finding.";
      resultsEl.appendChild(empty);
    }
    items.forEach((item) => resultsEl.appendChild(buildCard(item)));
  });
}

// ================= Geolocate: photo -> places on a map =================
// Step 1 (server): EXIF GPS, OCR, GeoCLIP. Step 2 (browser -> local Ollama
// vision model): visible clues and place names. Step 3 (server): geocode the
// names with OpenStreetMap and fuse every source into ranked candidates.
const GEO_KINDS = ["business", "landmark", "street", "district", "city", "region", "country"];
let geoMap = null;
let geoLayer = null;

function geoStep(text) {
  const list = document.getElementById("geo-steps");
  list.classList.remove("hidden");
  const li = document.createElement("li");
  li.textContent = text;
  li.className = "run";
  list.appendChild(li);
  return {
    done(note) { li.className = "done"; if (note) li.textContent = `${text} — ${note}`; },
    fail(note) { li.className = "fail"; li.textContent = `${text} — ${note}`; },
  };
}

function geoReset() {
  document.getElementById("geo-steps").innerHTML = "";
  document.getElementById("geo-error").classList.add("hidden");
  document.getElementById("geo-list").innerHTML = "";
  document.getElementById("geo-clues").innerHTML = "";
}

function geoRender(candidates, preview) {
  const layout = document.getElementById("geo-layout");
  layout.classList.remove("hidden");
  if (preview) document.getElementById("geo-preview").src = `data:image/jpeg;base64,${preview}`;
  if (typeof L === "undefined") {
    document.getElementById("geo-map").textContent = "Map library failed to load.";
  } else {
    if (!geoMap) {
      geoMap = L.map("geo-map", { worldCopyJump: true }).setView([41.3, 64.5], 4);
      L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        attribution: "&copy; OpenStreetMap contributors",
      }).addTo(geoMap);
    }
    if (geoLayer) geoLayer.remove();
    geoLayer = L.featureGroup().addTo(geoMap);
  }
  const list = document.getElementById("geo-list");
  list.innerHTML = "";
  if (!candidates.length) {
    list.textContent = "No location could be estimated from this photo.";
    return;
  }
  const colors = { high: "#34d399", medium: "#fbbf24", low: "#8b93b8" };
  candidates.slice(0, 8).forEach((c, i) => {
    const card = document.createElement("div");
    card.className = "geo-cand";
    const title = document.createElement("h4");
    title.textContent = `#${i + 1} ${c.label || `${c.lat}, ${c.lon}`}`;
    const meta = document.createElement("div");
    meta.className = "geo-meta";
    const conf = document.createElement("span");
    conf.className = `geo-conf-${c.confidence}`;
    conf.textContent = `${c.confidence} confidence`;
    meta.append(conf, ` · ±${c.radius_m >= 1000 ? Math.round(c.radius_m / 1000) + " km" : c.radius_m + " m"}` +
      ` · ${c.sources.join(" + ")}` + (c.agrees_with ? ` · agrees with ${c.agrees_with.join(", ")}` : ""));
    const ev = document.createElement("ul");
    c.evidence.slice(0, 4).forEach((e) => {
      const li = document.createElement("li");
      li.textContent = e;
      ev.appendChild(li);
    });
    const links = document.createElement("div");
    links.className = "geo-links";
    Object.entries(c.links || {}).slice(0, 5).forEach(([label, href]) => {
      const a = document.createElement("a");
      a.href = href;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.textContent = `${label} ↗`;
      links.appendChild(a);
    });
    card.append(title, meta, ev, links);
    list.appendChild(card);
    if (geoLayer) {
      const color = colors[c.confidence] || colors.low;
      const marker = L.circleMarker([c.lat, c.lon], { radius: 7, color, fillOpacity: 0.9 })
        .bindTooltip(`#${i + 1} ${c.confidence}`);
      const area = L.circle([c.lat, c.lon], { radius: Math.max(c.radius_m, 30), color, weight: 1, fillOpacity: 0.08 });
      geoLayer.addLayer(area).addLayer(marker);
      card.addEventListener("click", () => geoMap.fitBounds(area.getBounds(), { maxZoom: 16 }));
    }
  });
  if (geoLayer && geoLayer.getLayers().length) {
    const best = candidates[0];
    const bestArea = L.circle([best.lat, best.lon], { radius: Math.max(best.radius_m, 30) });
    geoMap.fitBounds(bestArea.getBounds(), { maxZoom: 15 });
    setTimeout(() => geoMap.invalidateSize(), 50);
  }
}

async function geoVision(step1) {
  const { url, vision } = ollamaConfig();
  const schema = {
    type: "object",
    properties: {
      clues: { type: "array", items: { type: "object", properties: {
        clue: { type: "string" }, points_to: { type: "string" } }, required: ["clue", "points_to"] } },
      places: { type: "array", items: { type: "object", properties: {
        name: { type: "string" }, kind: { type: "string", enum: GEO_KINDS },
        city: { type: "string" }, country: { type: "string" },
        confidence: { type: "number" }, evidence: { type: "string" } },
        required: ["name", "kind", "confidence", "evidence"] } },
      country_codes: { type: "array", items: { type: "string" } },
    },
    required: ["clues", "places", "country_codes"],
  };
  const hints = (step1.text_hints || []).map((h) => `${h.country} (${h.evidence})`).join("; ");
  const prompt =
    "You are a photo geolocation analyst. Use ONLY what is visible: text on signs and " +
    "shops, language and script, architecture, road markings and signs, licence-plate " +
    "format, vehicles, vegetation, terrain, landmarks. Do not identify any person.\n" +
    `OCR text read from the photo: "${(step1.ocr_text || "").slice(0, 500)}"\n` +
    (hints ? `Text hints: ${hints}\n` : "") +
    "Return: clues (each visible clue and what it points to); places (at most 5, the most " +
    "specific first: a business or landmark name you can actually read, then street, district, " +
    "city, region, country) with the exact visible evidence and a confidence 0-1; " +
    "country_codes (ISO 3166-1 alpha-2) of likely countries. If unsure, give a broader kind " +
    "with low confidence instead of guessing a specific place.";
  const response = await fetch(`${url}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      model: vision,
      messages: [{ role: "user", content: prompt, images: [step1.preview_b64] }],
      stream: false,
      format: schema,
      options: { temperature: 0.1 },
    }),
  });
  if (!response.ok) throw new Error(`Ollama returned HTTP ${response.status}`);
  const payload = await response.json();
  return JSON.parse((payload.message && payload.message.content) || "{}");
}

async function geolocateRun(form) {
  geoReset();
  const errorBox = document.getElementById("geo-error");
  let step1;
  const s1 = geoStep("Reading GPS, text and visual features on the server");
  try {
    const response = await fetch(`${API_BASE}/api/geolocate`, { method: "POST", headers: authHeaders(), body: form });
    step1 = await response.json();
    if (!response.ok || step1.status !== "success") throw new Error(step1.message || `HTTP ${response.status}`);
    const exif = step1.candidates.some((c) => c.sources.includes("EXIF GPS"));
    s1.done(exif ? "GPS found in the photo" : `${step1.candidates.length} visual guess(es), OCR ${step1.ocr_text ? "found text" : "found no text"}`);
  } catch (err) {
    s1.fail(err.message);
    errorBox.textContent = `Could not analyze the image: ${err.message}`;
    errorBox.classList.remove("hidden");
    return;
  }
  document.getElementById("geo-notice").textContent = step1.notice || "";
  geoRender(step1.candidates, step1.preview_b64);
  (step1.warnings || []).forEach((w) => geoStep(w).fail("note"));

  if (step1.vision === "server") {
    // the server already ran the local vision model and refined the result
    geoStep("Clues from the local vision model (run on the server)").done(
      `${(step1.clues || []).length} clue(s)`);
    const box = document.getElementById("geo-clues");
    box.innerHTML = "";
    (step1.clues || []).forEach((c) => {
      const p = document.createElement("p");
      p.textContent = `• ${c.clue} → ${c.points_to}`;
      box.appendChild(p);
    });
    return;
  }
  if (!step1.preview_b64) return;
  let vision;
  const s2 = geoStep("Looking for clues with the local vision model");
  try {
    vision = await geoVision(step1);
    s2.done(`${(vision.places || []).length} place(s), ${(vision.clues || []).length} clue(s)`);
  } catch (err) {
    s2.fail(`skipped (${err.message}). Pull it with: ollama pull qwen2.5vl:7b`);
    return;
  }
  const clues = document.getElementById("geo-clues");
  clues.innerHTML = "";
  (vision.clues || []).slice(0, 10).forEach((c) => {
    const p = document.createElement("p");
    p.textContent = `• ${c.clue} → ${c.points_to}`;
    clues.appendChild(p);
  });

  const s3 = geoStep("Finding those places on OpenStreetMap and combining all sources");
  try {
    const codes = [...new Set([...(vision.country_codes || []),
      ...(step1.text_hints || []).map((h) => h.country).filter((c) => /^[A-Z]{2}$/.test(c))])]
      .filter((c) => /^[A-Za-z]{2}$/.test(c)).slice(0, 3);
    const response = await fetch(`${API_BASE}/api/geolocate/refine`, {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ candidates: step1.raw_candidates || [], places: (vision.places || []).slice(0, 6),
                             country_codes: codes }),
    });
    const step3 = await response.json();
    if (!response.ok || step3.status !== "success") throw new Error(step3.message || `HTTP ${response.status}`);
    s3.done(`${step3.candidates.length} candidate place(s)`);
    (step3.warnings || []).forEach((w) => geoStep(w).fail("note"));
    geoRender(step3.candidates, null);
  } catch (err) {
    s3.fail(err.message);
  }
}

(function setupGeolocate() {
  const drop = document.getElementById("geo-drop");
  const fileInput = document.getElementById("geo-file");
  if (!drop || !fileInput) return;
  const runFile = (file) => {
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    geolocateRun(form);
  };
  document.getElementById("geo-pick").addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", () => runFile(fileInput.files[0]));
  document.getElementById("geo-url-go").addEventListener("click", () => {
    const value = document.getElementById("geo-url").value.trim();
    if (!value) return;
    const form = new FormData();
    form.append("url", value);
    geolocateRun(form);
  });
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => {
    e.preventDefault();
    drop.classList.add("dragover");
  }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => {
    e.preventDefault();
    drop.classList.remove("dragover");
  }));
  drop.addEventListener("drop", (e) => runFile(e.dataTransfer.files[0]));
})();


// ---- Data: access, Agent runs, audit log, full deletion (ROADMAP 8.2-8.4) ----

const dataEls = {
  whoami: document.getElementById("data-whoami"),
  key: document.getElementById("data-key"),
  runs: document.getElementById("data-runs"),
  auditUser: document.getElementById("data-audit-user"),
  auditQ: document.getElementById("data-audit-q"),
  audit: document.getElementById("data-audit"),
  auditError: document.getElementById("data-audit-error"),
  auditHint: document.getElementById("data-audit-hint"),
  auditMore: document.getElementById("data-audit-more"),
  wipeConfirm: document.getElementById("data-wipe-confirm"),
  wipeAudit: document.getElementById("data-wipe-audit"),
  wipeBtn: document.getElementById("data-wipe-btn"),
  wipeResult: document.getElementById("data-wipe-result"),
};
let auditOldestId = 0;

function dataApi(path, options = {}) {
  return requestJson(`${API_BASE}${path}`, {
    ...options,
    headers: authHeaders({ "Content-Type": "application/json" }),
  });
}

async function loadDataPanel() {
  let me = null;
  try {
    me = await dataApi("/api/whoami");
    dataEls.whoami.textContent = me.keys_configured
      ? `Signed in as ${me.user}${me.admin ? " (admin)" : ""}.`
      : "No API keys are set on the server: open to this machine and the local network only.";
  } catch (err) {
    dataEls.whoami.textContent = err.message;
  }
  loadDataRuns();
  if (me && me.admin) {
    dataEls.auditHint.textContent =
      `Who searched what and when. Stored only on this server, kept ${me.audit_retention_days} days.`;
    loadAudit(false);
  } else if (me) {
    dataEls.auditHint.textContent = "Only the admin key can read the audit log and delete all data.";
    dataEls.audit.replaceChildren();
  }
}

async function loadDataRuns() {
  dataEls.runs.replaceChildren();
  let runs = [];
  try {
    runs = (await dataApi("/api/agent?limit=50")).runs || [];
  } catch (err) {
    dataEls.runs.textContent = err.message;
    return;
  }
  if (!runs.length) {
    dataEls.runs.innerHTML = '<div class="empty-state">No Agent runs stored.</div>';
    return;
  }
  runs.forEach((run) => {
    const row = document.createElement("div");
    row.className = "data-row";
    const text = document.createElement("span");
    text.className = "data-row-text";
    text.textContent = run.text;
    const meta = document.createElement("span");
    meta.className = "data-row-meta";
    meta.textContent = `${formatRetrieved(run.created_at)} · ${run.status}`;
    const del = document.createElement("button");
    del.type = "button";
    del.className = "ghost";
    del.textContent = "Delete";
    del.addEventListener("click", async () => {
      del.disabled = true;
      try {
        await dataApi(`/api/agent/${encodeURIComponent(run.id)}`, { method: "DELETE" });
        row.remove();
      } catch (err) {
        del.disabled = false;
        meta.textContent = err.message;
      }
    });
    row.append(text, meta, del);
    dataEls.runs.appendChild(row);
  });
}

async function loadAudit(older) {
  const params = new URLSearchParams({ limit: "100" });
  if (dataEls.auditUser.value.trim()) params.set("user", dataEls.auditUser.value.trim());
  if (dataEls.auditQ.value.trim()) params.set("q", dataEls.auditQ.value.trim());
  if (older && auditOldestId) params.set("before", String(auditOldestId));
  dataEls.auditError.classList.add("hidden");
  let entries = [];
  try {
    entries = (await dataApi(`/api/audit?${params}`)).entries || [];
  } catch (err) {
    dataEls.auditError.textContent = `[ERROR] ${err.message}`;
    dataEls.auditError.classList.remove("hidden");
    return;
  }
  if (!older) {
    dataEls.audit.innerHTML =
      "<thead><tr><th>When (UTC)</th><th>User</th><th>Action</th><th>What</th><th>Status</th></tr></thead><tbody></tbody>";
  }
  const body = dataEls.audit.querySelector("tbody");
  entries.forEach((e) => {
    const tr = document.createElement("tr");
    [formatRetrieved(e.at).replace(" UTC", ""), e.user, `${e.method} ${e.path}${e.action ? " · " + e.action : ""}`,
     e.query || "", String(e.status ?? "")].forEach((value, i) => {
      const td = document.createElement("td");
      td.textContent = value;
      if (i === 4 && Number(value) >= 400) td.className = "bad";
      tr.appendChild(td);
    });
    body.appendChild(tr);
  });
  if (entries.length) auditOldestId = entries[entries.length - 1].id;
  if (!older && !entries.length) {
    body.innerHTML = '<tr><td colspan="5">No entries.</td></tr>';
  }
  dataEls.auditMore.classList.toggle("hidden", entries.length < 100);
}

document.getElementById("data-key-save").addEventListener("click", () => {
  try {
    localStorage.setItem(API_KEY_STORAGE, dataEls.key.value.trim());
  } catch (err) {
    /* storage blocked: the key lasts until reload */
  }
  dataEls.key.value = "";
  loadDataPanel();
});
document.getElementById("data-key-clear").addEventListener("click", () => {
  try {
    localStorage.removeItem(API_KEY_STORAGE);
  } catch (err) {
    /* nothing stored */
  }
  loadDataPanel();
});
document.getElementById("data-audit-load").addEventListener("click", () => loadAudit(false));
dataEls.auditMore.addEventListener("click", () => loadAudit(true));
dataEls.wipeConfirm.addEventListener("input", () => {
  dataEls.wipeBtn.disabled = dataEls.wipeConfirm.value.trim() !== "DELETE ALL";
});
dataEls.wipeBtn.addEventListener("click", async () => {
  dataEls.wipeBtn.disabled = true;
  try {
    const res = await dataApi("/api/data", {
      method: "DELETE",
      body: JSON.stringify({ confirm: dataEls.wipeConfirm.value.trim(), include_audit: dataEls.wipeAudit.checked }),
    });
    const d = res.deleted || {};
    dataEls.wipeResult.textContent =
      `Deleted: ${d.cases || 0} cases, ${d.findings || 0} findings, ${d.watches || 0} watches, ` +
      `${d.agent_runs || 0} Agent runs, ${res.cache_keys || 0} cached answers` +
      (d.audit_log != null ? `, ${d.audit_log} audit entries` : "") + "." +
      (res.warning ? ` ${res.warning}` : "");
    dataEls.wipeConfirm.value = "";
    loadDataPanel();
  } catch (err) {
    dataEls.wipeResult.textContent = err.message;
    dataEls.wipeBtn.disabled = false;
  }
});

// Globe (gods-eye-view, optional "geo" compose profile): show the link only
// when that service answers on this host. no-cors: we only learn "reachable".
(function globeLink() {
  const link = document.getElementById("globe-link");
  if (!link) return;
  const url = `${location.protocol}//${location.hostname}:4173/`;
  fetch(url, { mode: "no-cors", cache: "no-store" })
    .then(() => { link.href = url; link.hidden = false; })
    .catch(() => {});
})();

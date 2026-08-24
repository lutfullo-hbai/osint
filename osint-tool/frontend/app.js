const API_BASE = "http://localhost:8000";

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

function renderResults(panel, data) {
  const queryText = data.query != null ? `"${data.query}"` : "your query";
  panel.summary.innerHTML = `<strong>${data.count}</strong> result${
    data.count === 1 ? "" : "s"
  } for ${escapeHtml(queryText)}`;

  if (!data.results.length) {
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

async function handleSubmit(event) {
  event.preventDefault();
  const panel = getPanel(event.currentTarget.closest(".panel").id.replace("panel-", ""));
  const query = panel.input.value.trim();
  const endpoint = panel.form.dataset.endpoint;

  clearPanel(panel);
  if (!query) {
    showError(panel, "Please enter a value before searching.");
    return;
  }

  if (panel.controller) {
    panel.controller.abort();
  }
  panel.controller = new AbortController();

  setLoading(panel, true);
  try {
    const response = await fetch(`${API_BASE}${endpoint}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
      signal: panel.controller.signal,
    });

    let data;
    try {
      data = await response.json();
    } catch (parseError) {
      showError(panel, `Backend returned a non-JSON response (HTTP ${response.status}).`);
      return;
    }

    if (!response.ok || data.status !== "success") {
      showError(panel, data.message || `Request failed with HTTP ${response.status}.`);
      return;
    }

    renderResults(panel, data);
  } catch (err) {
    if (err.name === "AbortError") return;
    showError(
      panel,
      `Could not reach the backend at ${API_BASE}. Make sure it is running (docker-compose up).`
    );
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
    const response = await fetch(`${API_BASE}/api/catalog`);
    const data = await response.json();
    if (!response.ok || data.status !== "success") {
      throw new Error(data.message || "failed");
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

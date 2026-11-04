"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const state = { status: null, run: null, sort: "match", filter: "all" };

const LEVELS = { same: "Same product", strong: "Strong match", good: "Good match", partial: "Partial match" };
const MAX_COLS = 4;
const BOX_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 7.5 12 3l9 4.5v9L12 21l-9-4.5v-9Zm0 0 9 4.5m0 0 9-4.5M12 12v9" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg>';

// ---------------------------------------------------------------- helpers

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function money(v, cur = "USD") {
  if (v == null) return "No price";
  try { return new Intl.NumberFormat("en-US", { style: "currency", currency: cur || "USD" }).format(v); }
  catch { return `$${Number(v).toFixed(2)}`; }
}
function safeUrl(u) {
  try { const p = new URL(u); return p.protocol === "http:" || p.protocol === "https:" ? p.href : null; } catch { return null; }
}
function thumb(src, cls = "thumb") {
  const url = safeUrl(src);
  return url
    ? `<img class="${cls}" src="${esc(url)}" alt="" loading="lazy" referrerpolicy="no-referrer">`
    : `<div class="${cls} blank">${BOX_ICON}</div>`;
}
// Broken product images fall back to the box icon (no inline handlers, so CSP stays strict).
document.addEventListener("error", (e) => {
  const img = e.target;
  if (img instanceof HTMLImageElement && img.classList.contains("thumb")) {
    const div = document.createElement("div");
    div.className = `${img.className} blank`;
    div.innerHTML = BOX_ICON;
    img.replaceWith(div);
  }
}, true);

async function api(path, options = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  if (res.status === 401) {
    location.href = "/login";
    throw new Error("Please sign in.");
  }
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Something went wrong (HTTP ${res.status}).`);
  return data;
}

function setStatus(html, kind = "") {
  const el = $("#status");
  el.innerHTML = html;
  el.className = `status ${kind}`;
}

// ---------------------------------------------------------------- theme

const THEMES = ["system", "light", "dark"];
const THEME_LABEL = { system: "auto", light: "light", dark: "dark" };
function currentTheme() {
  try { return localStorage.getItem("theme") || "system"; } catch { return "system"; }
}
function applyTheme(t) {
  if (t === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = t;
  $("#theme").innerHTML = `<span class="theme-prefix">Theme: </span>${THEME_LABEL[t]}`;
}
$("#theme").addEventListener("click", () => {
  const next = THEMES[(THEMES.indexOf(currentTheme()) + 1) % THEMES.length];
  try { localStorage.setItem("theme", next); } catch { /* not saved; still applied */ }
  applyTheme(next);
});
applyTheme(currentTheme());

// ---------------------------------------------------------------- account & status

const accountBtn = $("#account-btn");
accountBtn.addEventListener("click", () => {
  const open = $("#account-menu").hidden;
  $("#account-menu").hidden = !open;
  accountBtn.setAttribute("aria-expanded", String(open));
});
document.addEventListener("click", (e) => {
  if (!e.target.closest(".account")) { $("#account-menu").hidden = true; accountBtn.setAttribute("aria-expanded", "false"); }
});
$("#logout").addEventListener("click", async () => {
  await fetch("/api/logout", { method: "POST" }).catch(() => {});
  location.href = "/login";
});

async function loadStatus() {
  const s = await api("/api/status");
  state.status = s;
  $("#username").textContent = s.user;
  $("#avatar").textContent = (s.user || "?").slice(0, 1);
  $("#ai-toggle").hidden = !s.ai_ready;
  renderUsage();
  if (!s.search_ready) {
    $("#setup").hidden = false;
    $("#setup").innerHTML = `Searching stores isn't set up on this server yet: it needs a SerpApi key in its settings
      (<code>SERPAPI_API_KEY</code>). Until then, <strong>Try with sample data</strong> shows how results look.`;
  }
}

function renderUsage() {
  const s = state.status;
  if (!s || !s.daily_limit) return;
  const used = Math.min(s.searches_today, s.daily_limit);
  const el = $("#usage");
  el.hidden = false;
  el.classList.toggle("full", used >= s.daily_limit);
  el.title = "Searches in the last 24 hours. Sample-data searches and reopening saved searches don't count.";
  el.innerHTML = `<span class="usage-bar" aria-hidden="true"><i style="width:${(used / s.daily_limit) * 100}%"></i></span>
    <span class="usage-text">${used} of ${s.daily_limit} searches today</span>`;
}

// ---------------------------------------------------------------- history

async function loadHistory() {
  const rows = await api("/api/searches");
  $("#history-empty").hidden = rows.length > 0;
  $("#history").innerHTML = rows.map((r) => `
    <li>
      <button class="history-open" type="button" data-id="${r.id}" aria-current="${state.run && state.run.id === r.id}">
        <span class="h-title">${esc(r.title)}</span>
        <span class="h-meta">${new Date(r.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric" })}, ${r.match_count} results${r.best_price != null ? `, from ${money(r.best_price)}` : ""}${r.demo ? " (sample)" : ""}</span>
      </button>
      <button class="history-delete" type="button" data-delete="${r.id}" aria-label="Delete search: ${esc(r.title)}">×</button>
    </li>`).join("");
}

// ---------------------------------------------------------------- search

async function runSearch({ demo = false } = {}) {
  const url = $("#url").value.trim();
  const details = $("#details").value.trim();
  if (!demo && !url && !details) {
    setStatus("Paste a product link, or open “Add product name or specs” and type it.", "error");
    $("#url").focus();
    return;
  }
  const buttons = [$("#find-btn"), $("#demo-btn")];
  buttons.forEach((b) => (b.disabled = true));
  const steps = demo
    ? ["Loading sample results"]
    : ["Reading the product page", "Searching stores", "Comparing specs", "Getting store links"];
  let i = 0;
  const show = () => setStatus(`<span class="spinner" aria-hidden="true"></span><span>${steps[i]}…${demo ? "" : " This usually takes 15–40 seconds."}</span>`);
  show();
  const timer = setInterval(() => { i = Math.min(i + 1, steps.length - 1); show(); }, 5000);
  $("#results").innerHTML = `<div class="grid skeleton" aria-hidden="true">${"<div></div>".repeat(6)}</div>`;
  try {
    const run = await api("/api/find", {
      method: "POST",
      body: JSON.stringify({ url: url || null, details: details || null, use_ai: $("#use-ai").checked, demo }),
    });
    setStatus("");
    state.run = run;
    state.filter = "all";
    render();
    $("#results").focus({ preventScroll: true });
    $("#results").scrollIntoView({ behavior: "smooth", block: "start" });
    loadHistory();
    if (!demo) loadStatus();
  } catch (err) {
    setStatus(esc(err.message), "error");
    if (state.run) render(); else $("#results").innerHTML = "";
  } finally {
    clearInterval(timer);
    buttons.forEach((b) => (b.disabled = false));
  }
}

async function openSearch(id) {
  try {
    state.run = await api(`/api/searches/${id}`);
    state.filter = "all";
    render();
    loadHistory();
    $("#results").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    setStatus(esc(err.message), "error");
  }
}

// ---------------------------------------------------------------- rendering

function columns(run) {
  return (run.reference_specs || []).slice(0, MAX_COLS);
}

function render() {
  const run = state.run;
  if (!run) return;
  const cols = columns(run);
  let matches = [...run.matches];
  if (state.filter === "strong") matches = matches.filter((m) => m.level !== "partial" && m.level !== "good");
  if (state.filter === "same") matches = matches.filter((m) => m.level === "same");
  if (state.sort === "price") matches.sort((a, b) => (a.price ?? 1e12) - (b.price ?? 1e12));

  const realMatches = run.matches.filter((m) => m.level !== "partial" && m.price != null);
  const lowest = realMatches.length ? Math.min(...realMatches.map((m) => m.price)) : null;
  const counts = run.matches.reduce((acc, m) => ((acc[m.level] = (acc[m.level] || 0) + 1), acc), {});
  const tally = ["same", "strong", "good", "partial"].filter((l) => counts[l])
    .map((l) => `${counts[l]} ${LEVELS[l].toLowerCase()}`).join(", ");

  $("#results").innerHTML = `
    ${plate(run)}
    <div class="toolbar">
      <h2>${run.matches.length} products found</h2>
      <span class="tally">${esc(tally)}</span>
      <span class="grow"></span>
      <div class="segmented" role="group" aria-label="Show">
        ${[["all", "All"], ["strong", "Strong matches"], ["same", "Same product"]].map(([v, t]) =>
          `<button type="button" data-filter="${v}" aria-pressed="${state.filter === v}">${t}</button>`).join("")}
      </div>
      <label class="sr-only" for="sort">Sort by</label>
      <select id="sort" class="select">
        <option value="match" ${state.sort === "match" ? "selected" : ""}>Best match first</option>
        <option value="price" ${state.sort === "price" ? "selected" : ""}>Lowest price first</option>
      </select>
    </div>
    <div class="grid" role="table" aria-label="Similar products" style="--cols:${cols.length}">
      <div class="grid-row grid-head" role="row">
        <div role="columnheader">Product</div>
        ${cols.map((c) => `<div role="columnheader">${esc(c.label)}<span class="ref-val">${esc(c.value)}</span></div>`).join("")}
        <div role="columnheader" style="text-align:right">Price</div>
        <div role="columnheader"><span class="sr-only">Links</span></div>
      </div>
      ${matches.length ? matches.map((m) => row(m, cols, lowest)).join("")
        : `<div class="grid-row"><div class="cell" style="grid-column:1/-1">No products at this filter. Choose “All” to see everything found.</div></div>`}
    </div>`;
}

function plate(run) {
  const ref = run.reference;
  const refUrl = safeUrl(ref.url);
  const specs = (run.reference_specs || []);
  const credits = run.demo ? "sample data" : `${run.searches_used} search credits used`;
  return `
    <section class="plate" aria-label="Reference product">
      <div class="plate-head">
        ${thumb(ref.image)}
        <div>
          <div class="plate-kicker">Your reference</div>
          <h2 class="plate-title">${esc(ref.title)}</h2>
          <div class="plate-meta">
            ${ref.brand ? `<span>${esc(ref.brand)}</span>` : ""}
            ${refUrl ? `<a href="${esc(refUrl)}" target="_blank" rel="noopener noreferrer">Open on ${esc(ref.store || "store")}</a>` : ""}
            <span>${run.candidates_found} products checked</span>
            <span>${esc(credits)}</span>
            ${run.ai_used ? "<span>Judged by Claude</span>" : ""}
          </div>
        </div>
        ${ref.price != null ? `<div class="plate-price"><strong>${money(ref.price, ref.currency)}</strong><span>reference price</span></div>` : ""}
      </div>
      ${specs.length ? `<div class="specs">${specs.map((s) =>
        `<div class="spec"><span class="spec-value">${esc(s.value)}</span><span class="spec-label">${esc(s.label)}</span></div>`).join("")}</div>` : ""}
      <div class="plate-foot">
        ${run.summary ? `<p class="plate-summary">${esc(run.summary)}</p>` : ""}
        ${!specs.length ? "<p>No specs recognized, so matches are based on the product name. Adding specs in the details box gives better results.</p>" : ""}
        ${run.notes.length ? `<ul>${run.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}
        <details><summary>Searches used</summary><ul>${run.queries.map((q) => `<li>${esc(q)}</li>`).join("")}</ul></details>
      </div>
    </section>`;
}

function row(m, cols, lowest) {
  const direct = safeUrl(m.link);
  const google = safeUrl(m.google_link);
  const byFeature = Object.fromEntries(m.comparisons.map((c) => [c.feature, c]));
  const cells = cols.map((col) => {
    const c = byFeature[col.feature];
    if (!c) return `<div class="speccell unknown" role="cell" data-label="${esc(col.label)}"><span class="mark" aria-hidden="true">–</span><span>Not stated</span></div>`;
    const mark = c.match === "yes" ? "✓" : c.match === "partial" ? "≈" : "✗";
    const word = c.match === "yes" ? "matches" : c.match === "partial" ? "close" : "differs";
    return `<div class="speccell ${c.match}" role="cell" data-label="${esc(col.label)}"><span class="mark" aria-hidden="true">${mark}</span><span>${esc(c.candidate)}<span class="sr-only"> (${word})</span></span></div>`;
  }).join("");
  const delta = m.price_vs_reference;
  const isLowest = lowest != null && m.price === lowest && m.level !== "partial";
  const offers = m.offers.length > 1 ? `
    <details><summary>Compare ${m.offers.length} stores, from ${money(m.offers[0].price, m.currency)}</summary>
      <table class="offers">${m.offers.map((o) => {
        const l = safeUrl(o.link);
        return `<tr><td>${l ? `<a href="${esc(l)}" target="_blank" rel="noopener noreferrer">${esc(o.store)}</a>` : esc(o.store)}</td>
          <td>${esc(o.shipping || "")}</td><td>${money(o.price, m.currency)}</td></tr>`;
      }).join("")}</table>
    </details>` : "";
  const notes = [
    m.reason ? `<div>${esc(m.reason)}</div>` : "",
    m.differences.length ? `<div>Differences: ${m.differences.map(esc).join("; ")}</div>` : "",
    offers,
  ].join("");

  return `
    <div class="grid-row" role="row" data-id="${m.id}">
      <div class="cell product" role="cell">
        ${thumb(m.thumbnail, "thumb s")}
        <div>
          <div class="p-title">${esc(m.title)}</div>
          <div class="p-meta">
            <span class="level ${m.level}">${LEVELS[m.level]}</span>
            <span class="pct" title="${m.ai_score != null ? `Claude ${Math.round(m.ai_score * 100)}%, spec rules ${Math.round(m.rule_score * 100)}%` : "Based on matching specs and name"}">${Math.round(m.score * 100)}% match</span>
            <span>${esc(m.store || "Unknown store")}</span>
            ${m.rating ? `<span>★ ${m.rating}${m.reviews ? ` (${m.reviews.toLocaleString()})` : ""}</span>` : ""}
            ${m.condition ? `<span>${esc(m.condition)}</span>` : ""}
          </div>
        </div>
      </div>
      <div class="specs-wrap">${cells}</div>
      <div class="cell pricecell" role="cell">
        <div class="price">${money(m.price, m.currency)}</div>
        ${m.old_price ? `<span class="was">${money(m.old_price, m.currency)}</span>` : ""}
        ${delta != null && delta !== 0 ? `<span class="delta ${delta < 0 ? "down" : "up"}">${money(Math.abs(delta), m.currency)} ${delta < 0 ? "less" : "more"}</span>` : ""}
        ${m.delivery ? `<span class="delta" style="color:var(--zinc-500);font-weight:400">${esc(m.delivery)}</span>` : ""}
        ${isLowest ? `<span class="lowest">Lowest price</span>` : ""}
      </div>
      <div class="cell actions" role="cell">
        ${direct ? `<a class="btn btn-primary btn-s" href="${esc(direct)}" target="_blank" rel="noopener noreferrer">View at store</a>`
                 : m.page_token ? `<button class="btn btn-primary btn-s" type="button" data-action="link">Get store link</button>` : ""}
        ${google ? `<a class="btn btn-quiet btn-s alt" href="${esc(google)}" target="_blank" rel="noopener noreferrer">Google Shopping</a>` : ""}
      </div>
      ${notes ? `<div class="extra">${notes}</div>` : ""}
    </div>`;
}

// ---------------------------------------------------------------- events

$("#find-form").addEventListener("submit", (e) => { e.preventDefault(); runSearch(); });
$("#demo-btn").addEventListener("click", () => runSearch({ demo: true }));

$("#history").addEventListener("click", async (e) => {
  const del = e.target.closest("[data-delete]");
  if (del) {
    const id = Number(del.dataset.delete);
    try {
      await api(`/api/searches/${id}`, { method: "DELETE" });
      if (state.run && state.run.id === id) {
        state.run = null;
        $("#results").innerHTML = `<div class="empty"><h2>Search deleted</h2><p>Run a new search, or open another one from the list.</p></div>`;
      }
      loadHistory();
    } catch (err) { setStatus(esc(err.message), "error"); }
    return;
  }
  const open = e.target.closest(".history-open");
  if (open) openSearch(Number(open.dataset.id));
});

$("#results").addEventListener("change", (e) => {
  if (e.target.id === "sort") { state.sort = e.target.value; render(); }
});

$("#results").addEventListener("click", async (e) => {
  const filter = e.target.closest("[data-filter]");
  if (filter) { state.filter = filter.dataset.filter; render(); return; }
  const btn = e.target.closest('button[data-action="link"]');
  if (!btn) return;
  const id = Number(btn.closest("[data-id]").dataset.id);
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner" aria-hidden="true"></span>Finding link';
  try {
    const updated = await api(`/api/searches/${state.run.id}/matches/${id}/store-link`, { method: "POST" });
    state.run.matches = state.run.matches.map((m) => (m.id === id ? updated : m));
    render();
  } catch (err) {
    btn.disabled = false;
    btn.textContent = "Get store link";
    setStatus(esc(err.message), "error");
  }
});

loadStatus().catch((err) => setStatus(esc(err.message), "error"));
loadHistory().catch(() => {});

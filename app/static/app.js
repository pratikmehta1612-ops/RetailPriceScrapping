"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const state = { status: null, run: null, sort: "match", showPartial: true };

const LEVELS = {
  same: "Same product",
  strong: "Strong match",
  good: "Good match",
  partial: "Partial match",
};

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function money(v, cur = "USD") {
  if (v == null) return "—";
  try { return new Intl.NumberFormat("en-US", { style: "currency", currency: cur || "USD" }).format(v); }
  catch { return `$${Number(v).toFixed(2)}`; }
}
function safeUrl(u) {
  try { const p = new URL(u); return p.protocol === "http:" || p.protocol === "https:" ? p.href : null; } catch { return null; }
}
function thumb(src, cls = "thumb") {
  const url = safeUrl(src);
  return url
    ? `<img class="${cls}" src="${esc(url)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.outerHTML='<div class=&quot;${cls} blank&quot;>📦</div>'">`
    : `<div class="${cls} blank">📦</div>`;
}

async function api(path, options = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Request failed (HTTP ${res.status})`);
  return data;
}

function setStatus(html, kind = "") {
  const el = $("#status");
  el.innerHTML = html;
  el.className = `status ${kind}`;
}

// ---------------------------------------------------------------- status & setup

async function loadStatus() {
  const s = await api("/api/status");
  state.status = s;
  $("#status-chips").innerHTML = `
    <span class="pill ${s.search_ready ? "on" : "off"}">Search: ${s.search_ready ? "ready" : "no API key"}</span>
    <span class="pill ${s.ai_ready ? "on" : ""}">AI matching: ${s.ai_ready ? "on" : "off"}</span>`;
  $("#ai-toggle").hidden = !s.ai_ready;
  if (!s.search_ready) {
    $("#setup").hidden = false;
    $("#setup").innerHTML = `
      <h2>One step before your first real search</h2>
      <p class="small">Searching stores needs a free SerpApi key (250 searches a month, about 19 product searches).</p>
      <ol class="small">
        <li>Sign up at <a href="https://serpapi.com/users/sign_up" target="_blank" rel="noopener">serpapi.com</a> and copy your API key.</li>
        <li>In the project folder, copy <code>.env.example</code> to <code>.env</code> and set <code>SERPAPI_API_KEY=your-key</code>.</li>
        <li>Stop the server (Ctrl+C) and start it again.</li>
      </ol>
      <p class="small">Meanwhile, <strong>Try demo</strong> shows how results look using sample data.</p>`;
  }
}

// ---------------------------------------------------------------- history

async function loadHistory() {
  const rows = await api("/api/searches");
  $("#history-empty").hidden = rows.length > 0;
  $("#history").innerHTML = rows.map((r) => `
    <li><button type="button" data-id="${r.id}" aria-current="${state.run && state.run.id === r.id}">
      <div class="h-title">${esc(r.title)}</div>
      <div class="h-meta">${new Date(r.created_at).toLocaleDateString()} · ${r.match_count} results${r.best_price != null ? ` · from ${money(r.best_price)}` : ""}${r.demo ? " · demo" : ""}</div>
    </button></li>`).join("");
}

// ---------------------------------------------------------------- search

async function runSearch({ demo = false } = {}) {
  const url = $("#url").value.trim();
  const details = $("#details").value.trim();
  if (!demo && !url && !details) {
    setStatus("Paste a product link or type the product name.", "error");
    return;
  }
  const buttons = [$("#find-btn"), $("#demo-btn")];
  buttons.forEach((b) => (b.disabled = true));
  const steps = demo
    ? ["Loading sample results…"]
    : ["Reading the reference product…", "Searching stores…", "Comparing features…", "Finding store links…"];
  let i = 0;
  setStatus(`<span class="spinner"></span>${steps[0]}`);
  const timer = setInterval(() => { i = Math.min(i + 1, steps.length - 1); setStatus(`<span class="spinner"></span>${steps[i]} This usually takes 15–40 seconds.`); }, 4000);
  try {
    const run = await api("/api/find", {
      method: "POST",
      body: JSON.stringify({ url: url || null, details: details || null, use_ai: $("#use-ai").checked, demo }),
    });
    setStatus("");
    show(run);
    loadHistory();
  } catch (err) {
    setStatus(esc(err.message), "error");
  } finally {
    clearInterval(timer);
    buttons.forEach((b) => (b.disabled = false));
  }
}

async function openSearch(id) {
  try {
    show(await api(`/api/searches/${id}`));
    loadHistory();
    window.scrollTo({ top: 0, behavior: "smooth" });
  } catch (err) {
    setStatus(esc(err.message), "error");
  }
}

// ---------------------------------------------------------------- rendering

function show(run) {
  state.run = run;
  render();
}

function render() {
  const run = state.run;
  if (!run) { $("#results").innerHTML = ""; return; }
  const ref = run.reference;
  const refUrl = safeUrl(ref.url);
  const attrs = run.key_attributes.map((a) =>
    `<span class="attr ${a.importance === "must" ? "must" : ""}" title="${esc(a.importance)}"><b>${esc(a.name)}:</b> ${esc(a.value)}</span>`).join("");

  let matches = [...run.matches];
  if (!state.showPartial) matches = matches.filter((m) => m.level !== "partial");
  if (state.sort === "price") matches.sort((a, b) => (a.price ?? 1e12) - (b.price ?? 1e12));
  const counts = run.matches.reduce((acc, m) => ((acc[m.level] = (acc[m.level] || 0) + 1), acc), {});

  $("#results").innerHTML = `
    <article class="card reference">
      ${thumb(ref.image)}
      <div>
        <div class="eyebrow">Reference product</div>
        <h2>${esc(ref.title)}</h2>
        <div class="ref-meta">
          ${ref.brand ? `<span>${esc(ref.brand)}</span>` : ""}
          ${ref.price != null ? `<span><b>${money(ref.price, ref.currency)}</b></span>` : ""}
          ${refUrl ? `<a href="${esc(refUrl)}" target="_blank" rel="noopener">${esc(ref.store || "Open page")} ↗</a>` : ""}
          <span>${run.candidates_found} products checked · ${run.searches_used} search credits${run.ai_used ? " · AI matching" : ""}</span>
        </div>
        ${run.summary ? `<p class="small muted">${esc(run.summary)}</p>` : ""}
        <div class="attrs">${attrs || '<span class="muted small">No attributes detected; matching used the title.</span>'}</div>
        ${run.notes.length ? `<ul class="notes">${run.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}
        <details class="queries"><summary>Searches used</summary><ul>${run.queries.map((q) => `<li>${esc(q)}</li>`).join("")}</ul></details>
      </div>
    </article>

    <div class="toolbar">
      <h2>${run.matches.length} similar products</h2>
      <span class="muted small">${["same", "strong", "good", "partial"].filter((l) => counts[l]).map((l) => `${counts[l]} ${LEVELS[l].toLowerCase()}`).join(" · ")}</span>
      <span class="spacer"></span>
      <label><input type="checkbox" id="show-partial" ${state.showPartial ? "checked" : ""}> Show partial matches</label>
      <label>Sort <select id="sort">
        <option value="match" ${state.sort === "match" ? "selected" : ""}>Best match</option>
        <option value="price" ${state.sort === "price" ? "selected" : ""}>Lowest price</option>
      </select></label>
    </div>

    <div class="matches">
      ${matches.map((m) => matchCard(m, ref)).join("") || `<div class="card empty">No matches at this filter.</div>`}
    </div>`;
}

function matchCard(m, ref) {
  const direct = safeUrl(m.link);
  const google = safeUrl(m.google_link);
  const pct = Math.round(m.score * 100);
  const delta = m.price_vs_reference;
  const cmp = m.comparisons.map((c) =>
    `<span class="${c.match === "yes" ? "" : c.match}" title="Reference: ${esc(c.reference)} · This: ${esc(c.candidate)}">${c.match === "yes" ? "✓" : c.match === "partial" ? "≈" : "✗"} ${esc(c.label)}: ${esc(c.candidate)}</span>`).join("");
  const diffs = m.differences.length ? `<div class="reason">Differences: ${m.differences.map(esc).join("; ")}</div>` : "";
  const offers = m.offers.length > 1 ? `
    <details class="offers"><summary>${m.offers.length} stores from ${money(m.offers[0].price, m.currency)}</summary>
      <table>${m.offers.map((o) => `<tr><td>${safeUrl(o.link) ? `<a href="${esc(safeUrl(o.link))}" target="_blank" rel="noopener">${esc(o.store)}</a>` : esc(o.store)}</td>
        <td class="muted">${esc(o.shipping || "")}</td><td class="p">${money(o.price, m.currency)}</td></tr>`).join("")}</table>
    </details>` : "";

  return `
    <article class="card match" data-id="${m.id}">
      ${thumb(m.thumbnail, "thumb sm")}
      <div>
        <div class="m-title">${esc(m.title)}</div>
        <div class="m-store">
          <span class="badge ${m.level}">${LEVELS[m.level]}</span>
          <span>${esc(m.store || "Unknown store")}</span>
          ${m.rating ? `<span>★ ${m.rating}${m.reviews ? ` (${m.reviews.toLocaleString()})` : ""}</span>` : ""}
          ${m.delivery ? `<span>${esc(m.delivery)}</span>` : ""}
          ${m.condition ? `<span>${esc(m.condition)}</span>` : ""}
        </div>
        ${cmp ? `<div class="cmp">${cmp}</div>` : ""}
        ${m.reason ? `<div class="reason">${esc(m.reason)}</div>` : ""}
        ${diffs}
      </div>
      <div class="m-side">
        <div>
          <div class="price">${money(m.price, m.currency)}</div>
          ${m.old_price ? `<div class="old">${money(m.old_price, m.currency)}</div>` : ""}
        </div>
        ${delta != null && delta !== 0 ? `<span class="delta ${delta < 0 ? "cheaper" : "pricier"}">${delta < 0 ? "−" : "+"}${money(Math.abs(delta), m.currency)} vs reference</span>` : ""}
        <div class="score" title="${m.ai_score != null ? `AI ${Math.round(m.ai_score * 100)}% · rules ${Math.round(m.rule_score * 100)}%` : "Rule-based score"}">
          <div class="bar"><i style="width:${pct}%"></i></div>${pct}% match
        </div>
        <div class="links">
          ${direct ? `<a class="btn small primary" href="${esc(direct)}" target="_blank" rel="noopener">View at ${esc(m.store || "store")} ↗</a>`
                   : m.page_token ? `<button class="btn small primary" type="button" data-action="link">Get store link</button>` : ""}
          ${google ? `<a class="btn small" href="${esc(google)}" target="_blank" rel="noopener">Google Shopping ↗</a>` : ""}
        </div>
      </div>
      ${offers}
    </article>`;
}

// ---------------------------------------------------------------- events

$("#find-form").addEventListener("submit", (e) => { e.preventDefault(); runSearch(); });
$("#demo-btn").addEventListener("click", () => runSearch({ demo: true }));
$("#history").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-id]");
  if (btn) openSearch(Number(btn.dataset.id));
});
$("#results").addEventListener("change", (e) => {
  if (e.target.id === "sort") { state.sort = e.target.value; render(); }
  if (e.target.id === "show-partial") { state.showPartial = e.target.checked; render(); }
});
$("#results").addEventListener("click", async (e) => {
  const btn = e.target.closest('button[data-action="link"]');
  if (!btn) return;
  const id = Number(btn.closest(".match").dataset.id);
  btn.disabled = true;
  btn.textContent = "Looking up…";
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

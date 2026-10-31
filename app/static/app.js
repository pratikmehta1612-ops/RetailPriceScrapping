"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const state = { products: [], category: null, selected: null, minScore: 0.4 };

const RETAILER_NAMES = { amazon: "Amazon", walmart: "Walmart", target: "Target", bestbuy: "Best Buy" };
const CATEGORY_NAMES = {
  tire: "Tires", motor_oil: "Motor oil", battery: "Batteries", wiper_blade: "Wiper blades",
  brake_pads: "Brake pads", brake_rotor: "Brake rotors", oil_filter: "Oil filters",
  cabin_air_filter: "Cabin filters", engine_air_filter: "Air filters", spark_plug: "Spark plugs",
  headlight_bulb: "Bulbs", coolant: "Coolant", transmission_fluid: "Transmission fluid",
  brake_fluid: "Brake fluid", floor_mats: "Floor mats", dash_cam: "Dash cams",
  jump_starter: "Jump starters", car_charger: "Car chargers", other: "Other",
};

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
const money = (v, cur = "USD") =>
  v == null ? "—" : new Intl.NumberFormat("en-US", { style: "currency", currency: cur || "USD" }).format(v);
const label = (key) => key.replace(/_/g, " ").replace(/\b(in|mm|k)\b$/, (u) => `(${u})`);
const retailer = (r) => RETAILER_NAMES[r] || r;
const fmtValue = (v) => (Array.isArray(v) ? (v.length === 2 && typeof v[0] === "number" ? `${v[0]}–${v[1]}` : v.join(", ")) : v === true ? "yes" : v);

async function api(path, options = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || data));
  return data;
}

function setStatus(text, kind = "") {
  const el = $("#status");
  el.textContent = text;
  el.className = `status ${kind}`;
}

function thumb(src, cls = "thumb") {
  return src ? `<img class="${cls}" src="${esc(src)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.outerHTML='<div class=&quot;${cls} blank&quot;>🛞</div>'">`
             : `<div class="${cls} blank">🛞</div>`;
}

// ---------------------------------------------------------------- list

async function loadProducts() {
  state.products = await api("/api/products");
  renderChips();
  renderList();
}

function renderChips() {
  const counts = {};
  state.products.forEach((p) => (counts[p.category] = (counts[p.category] || 0) + 1));
  const chips = [["", `All ${state.products.length}`], ...Object.entries(counts).map(([c, n]) => [c, `${CATEGORY_NAMES[c] || c} ${n}`])];
  $("#chips").innerHTML = chips
    .map(([c, text]) => `<button class="chip" type="button" data-cat="${esc(c)}" aria-pressed="${(state.category || "") === c}">${esc(text)}</button>`)
    .join("");
}

function renderList() {
  const q = $("#filter").value.trim().toLowerCase();
  const items = state.products.filter(
    (p) => (!state.category || p.category === state.category) &&
           (!q || `${p.title} ${p.brand || ""} ${p.retailer}`.toLowerCase().includes(q)),
  );
  $("#empty").hidden = state.products.length > 0;
  $("#product-list").innerHTML = items
    .map((p) => `
      <li data-id="${p.id}" aria-selected="${state.selected === p.id}">
        ${thumb(p.image)}
        <div>
          <div class="p-title">${esc(p.title)}</div>
          <div class="p-meta"><span class="retailer">${esc(retailer(p.retailer))}</span> · ${esc(CATEGORY_NAMES[p.category] || p.category)}</div>
        </div>
        <div class="price">${money(p.price, p.currency)}
          ${p.unit_price != null ? `<span class="unit">${money(p.unit_price, p.currency)}/${esc(p.unit_label)}</span>` : ""}
        </div>
      </li>`)
    .join("");
}

// ---------------------------------------------------------------- detail

async function select(id) {
  state.selected = id;
  renderList();
  const pane = $("#detail");
  pane.innerHTML = `<p class="empty">Loading…</p>`;
  try {
    const [product, history, similar] = await Promise.all([
      api(`/api/products/${id}`),
      api(`/api/products/${id}/history`),
      api(`/api/products/${id}/similar?min_score=${state.minScore}`),
    ]);
    renderDetail(product, history, similar);
  } catch (err) {
    pane.innerHTML = `<p class="empty">${esc(err.message)}</p>`;
  }
}

function renderDetail(p, history, similar) {
  const features = Object.entries(p.features).filter(([k]) => k !== "gtin");
  $("#detail").innerHTML = `
    <div class="d-head">
      ${thumb(p.image)}
      <div>
        <span class="retailer">${esc(retailer(p.retailer))}</span>
        <h2>${esc(p.title)}</h2>
        <div class="d-price">${money(p.price, p.currency)}
          ${p.unit_price != null ? `<span class="unit">${money(p.unit_price, p.currency)} per ${esc(p.unit_label)}</span>` : ""}
        </div>
        <div class="p-meta">${esc(p.availability || "")} · updated ${new Date(p.updated_at).toLocaleString()}</div>
        <div class="d-actions">
          <a href="${esc(p.url)}" target="_blank" rel="noopener">View at ${esc(retailer(p.retailer))} ↗</a>
          <button class="btn small" type="button" data-action="refresh">Refresh price</button>
          <button class="btn small danger" type="button" data-action="delete">Remove</button>
        </div>
      </div>
    </div>

    <div class="section">
      <h3>Detected features · ${esc(CATEGORY_NAMES[p.category] || p.category)}</h3>
      ${features.length
        ? `<div class="features">${features.map(([k, v]) => `<div class="feature"><div class="k">${esc(label(k))}</div><div class="v">${esc(fmtValue(v))}</div></div>`).join("")}</div>`
        : `<p class="p-meta">No automotive features recognized. Similar-product matching will rely on the title.</p>`}
    </div>

    <div class="section">
      <h3>Price history</h3>
      ${chart(history, p.currency)}
    </div>

    <div class="section">
      <h3>Similar products at other stores</h3>
      <div class="sim-controls">
        <label for="min-score">Minimum match</label>
        <input id="min-score" type="range" min="0" max="1" step="0.05" value="${state.minScore}">
        <span>${Math.round(state.minScore * 100)}%</span>
      </div>
      ${similarTable(similar, p)}
    </div>`;
}

function chart(history, currency) {
  const pts = history.filter((h) => h.price != null);
  if (pts.length === 0) return `<p class="p-meta">No prices recorded yet.</p>`;
  if (pts.length === 1) return `<p class="p-meta">One price so far: ${money(pts[0].price, currency)} on ${new Date(pts[0].scraped_at).toLocaleDateString()}. Refresh later to build a history.</p>`;
  // Draw at the pane's real width so text isn't stretched or squashed.
  const W = Math.max(280, Math.round(($("#detail").clientWidth || 640) - 40)), H = 140, pad = { l: 56, r: 12, t: 10, b: 22 };
  const xs = pts.map((p) => new Date(p.scraped_at).getTime());
  const ys = pts.map((p) => p.price);
  const [x0, x1] = [Math.min(...xs), Math.max(...xs)];
  let [y0, y1] = [Math.min(...ys), Math.max(...ys)];
  if (y0 === y1) { y0 -= 1; y1 += 1; }
  const sx = (x) => pad.l + ((x - x0) / (x1 - x0 || 1)) * (W - pad.l - pad.r);
  const sy = (y) => pad.t + (1 - (y - y0) / (y1 - y0)) * (H - pad.t - pad.b);
  const line = pts.map((p, i) => `${i ? "L" : "M"}${sx(xs[i]).toFixed(1)},${sy(p.price).toFixed(1)}`).join("");
  const area = `${line}L${sx(xs.at(-1)).toFixed(1)},${H - pad.b}L${sx(xs[0]).toFixed(1)},${H - pad.b}Z`;
  const day = (t) => new Date(t).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Price history">
    <line class="grid" x1="${pad.l}" x2="${W - pad.r}" y1="${sy(y1)}" y2="${sy(y1)}"/>
    <line class="grid" x1="${pad.l}" x2="${W - pad.r}" y1="${sy(y0)}" y2="${sy(y0)}"/>
    <text x="4" y="${sy(y1) + 4}">${money(y1, currency)}</text>
    <text x="4" y="${sy(y0) + 4}">${money(y0, currency)}</text>
    <text x="${pad.l}" y="${H - 4}">${day(x0)}</text>
    <text x="${W - pad.r}" y="${H - 4}" text-anchor="end">${day(x1)}</text>
    <path class="area" d="${area}"/><path class="line" d="${line}"/>
    ${pts.map((p, i) => `<circle class="dot" cx="${sx(xs[i])}" cy="${sy(p.price)}" r="3"><title>${money(p.price, currency)} · ${new Date(p.scraped_at).toLocaleString()}</title></circle>`).join("")}
  </svg>`;
}

function similarTable(rows, base) {
  if (!rows.length) {
    return `<p class="p-meta">No similar ${esc(CATEGORY_NAMES[base.category] || "products")} saved yet. Add the same kind of product from other stores to compare.</p>`;
  }
  const perUnit = base.unit_label;
  return `<table class="sim-table">
    <thead><tr><th>Match</th><th>Product</th><th>Price</th><th class="hide-sm">vs this${perUnit ? ` (per ${esc(perUnit)})` : ""}</th></tr></thead>
    <tbody>${rows.map((r) => {
      const d = r.price_difference;
      const diff = d == null ? "—" : d === 0 ? "same" : `<span class="diff ${d < 0 ? "cheaper" : "pricier"}">${d < 0 ? "−" : "+"}${money(Math.abs(d), r.product.currency)}</span>`;
      return `<tr data-id="${r.product.id}">
        <td><div class="score"><div class="bar"><i style="width:${Math.round(r.score * 100)}%"></i></div>${Math.round(r.score * 100)}%</div></td>
        <td><span class="retailer">${esc(retailer(r.product.retailer))}</span> ${esc(r.product.title)}
          <div class="cmp">${r.comparisons.map((c) => `<span class="${c.match ? "" : "no"}" title="${esc(fmtValue(c.a))} vs ${esc(fmtValue(c.b))}">${c.match ? "✓" : "✗"} ${esc(label(c.feature))}</span>`).join("")}</div>
        </td>
        <td class="price">${money(r.product.price, r.product.currency)}
          ${r.product.unit_price != null ? `<span class="unit">${money(r.product.unit_price, r.product.currency)}/${esc(r.product.unit_label)}</span>` : ""}
          <span class="show-sm">${diff}</span></td>
        <td class="hide-sm">${diff}</td>
      </tr>`;
    }).join("")}</tbody></table>`;
}

// ---------------------------------------------------------------- events

$("#add-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = e.submitter;
  btn.disabled = true;
  setStatus("Fetching product page… (pages are fetched politely, this can take a few seconds)");
  try {
    const p = await api("/api/products", { method: "POST", body: JSON.stringify({ url: $("#add-url").value.trim() }) });
    setStatus(`Added: ${p.title}`, "ok");
    $("#add-url").value = "";
    await loadProducts();
    select(p.id);
  } catch (err) {
    setStatus(err.message, "error");
    if (/Import HTML/i.test(err.message)) { $("#import").open = true; $("#import-url").value = $("#add-url").value; }
  } finally {
    btn.disabled = false;
  }
});

$("#import-file").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (file) $("#import-html").value = await file.text();
});

$("#import-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const p = await api("/api/products/import", {
      method: "POST",
      body: JSON.stringify({ url: $("#import-url").value.trim(), html: $("#import-html").value }),
    });
    setStatus(`Imported: ${p.title}`, "ok");
    $("#import-html").value = "";
    $("#import-file").value = "";
    await loadProducts();
    select(p.id);
  } catch (err) {
    setStatus(err.message, "error");
  }
});

$("#refresh-all").addEventListener("click", async (e) => {
  e.target.disabled = true;
  setStatus("Refreshing every product… this waits a few seconds between requests to each store.");
  try {
    const r = await api("/api/refresh", { method: "POST" });
    setStatus(`Refreshed ${r.refreshed.length}, failed ${r.failed.length}.`, r.failed.length ? "error" : "ok");
    await loadProducts();
    if (state.selected) select(state.selected);
  } catch (err) {
    setStatus(err.message, "error");
  } finally {
    e.target.disabled = false;
  }
});

$("#filter").addEventListener("input", renderList);
$("#chips").addEventListener("click", (e) => {
  const chip = e.target.closest(".chip");
  if (!chip) return;
  state.category = chip.dataset.cat || null;
  renderChips();
  renderList();
});
$("#product-list").addEventListener("click", (e) => {
  const li = e.target.closest("li[data-id]");
  if (li) select(Number(li.dataset.id));
});

$("#detail").addEventListener("click", async (e) => {
  const row = e.target.closest("tr[data-id]");
  if (row) return select(Number(row.dataset.id));
  const action = e.target.dataset.action;
  if (!action || !state.selected) return;
  e.target.disabled = true;
  try {
    if (action === "refresh") {
      await api(`/api/products/${state.selected}/refresh`, { method: "POST" });
      setStatus("Price refreshed.", "ok");
      await loadProducts();
      select(state.selected);
    } else if (action === "delete" && confirm("Remove this product and its price history?")) {
      await api(`/api/products/${state.selected}`, { method: "DELETE" });
      state.selected = null;
      $("#detail").innerHTML = `<p class="empty">Product removed.</p>`;
      await loadProducts();
    }
  } catch (err) {
    setStatus(err.message, "error");
  } finally {
    e.target.disabled = false;
  }
});

$("#detail").addEventListener("change", (e) => {
  if (e.target.id === "min-score") {
    state.minScore = Number(e.target.value);
    select(state.selected);
  }
});

loadProducts().catch((err) => setStatus(err.message, "error"));

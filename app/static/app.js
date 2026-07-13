"use strict";

const $ = (sel) => document.querySelector(sel);

const gameSel = $("#game");
const form = $("#search-form");
const queryInput = $("#query");
const statusEl = $("#status");
const resultsEl = $("#results");
const modal = $("#modal");
const modalTitle = $("#modal-title");
const printingsEl = $("#printings");

function setStatus(msg) {
  statusEl.textContent = msg || "";
}

// --- search ---------------------------------------------------------------

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const game = gameSel.value;
  const q = queryInput.value.trim();
  if (!q) return;
  resultsEl.innerHTML = "";
  setStatus("Searching…");
  dbg("search", { game, q });
  try {
    const r = await fetch(`/api/search?game=${encodeURIComponent(game)}&q=${encodeURIComponent(q)}`);
    if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
    const { results } = await r.json();
    dbg("search results", results.length);
    setStatus(results.length ? `${results.length} result(s)` : "No cards found.");
    renderResults(results);
  } catch (err) {
    setStatus("Error: " + err.message);
  }
});

function renderResults(results) {
  for (const card of results) {
    const el = document.createElement("div");
    el.className = "card";
    el.innerHTML = `
      <div class="card-img">${card.image ? `<img loading="lazy" src="${card.image}" alt="${escapeHtml(card.name)}">` : ""}</div>
      <div class="card-name">${escapeHtml(card.name)}</div>
      <div class="card-sub">${(card.sets || []).join(", ")}</div>
    `;
    el.addEventListener("click", () => openPrintings(card));
    resultsEl.appendChild(el);
  }
}

// --- printings modal ------------------------------------------------------

async function openPrintings(card) {
  const game = gameSel.value;
  dbg("fetch printings", card.identifier);
  modalTitle.textContent = card.name;
  printingsEl.innerHTML = "<p class='status'>Loading printings…</p>";
  modal.classList.remove("hidden");
  try {
    const r = await fetch(`/api/printings?game=${encodeURIComponent(game)}&id=${encodeURIComponent(card.identifier)}`);
    if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
    const { printings } = await r.json();
    renderPrintings(card, printings);
  } catch (err) {
    printingsEl.innerHTML = `<p class="status">Error: ${escapeHtml(err.message)}</p>`;
  }
}

function renderPrintings(card, printings) {
  printingsEl.innerHTML = "";
  if (!printings.length) {
    printingsEl.innerHTML = "<p class='status'>No printings found.</p>";
    return;
  }
  for (const p of printings) {
    const el = document.createElement("div");
    el.className = "card";
    el.innerHTML = `
      <div class="card-img">${p.image ? `<img loading="lazy" src="${p.image}" alt="${escapeHtml(p.label)}">` : ""}</div>
      <div class="card-name">${escapeHtml(p.label)}</div>
      <div class="card-sub">${escapeHtml(p.rarity || "")}</div>
      <div class="price placeholder">— price TBD —</div>
      <button class="add-btn">Add to buylist</button>
    `;
    el.querySelector(".add-btn").addEventListener("click", (ev) => {
      ev.stopPropagation();
      openQtyPrompt(card, p);
    });
    printingsEl.appendChild(el);
  }
}

// --- quantity prompt ------------------------------------------------------

const qtyOverlay = $("#qty-overlay");
const qtyInput = $("#qty-input");
const qtyLabel = $("#qty-prompt-label");
let pendingAdd = null; // { card, p }

function openQtyPrompt(card, p) {
  pendingAdd = { card, p };
  qtyLabel.textContent = `${card.name} — ${p.label}`;
  qtyInput.value = "1";
  qtyOverlay.classList.remove("hidden");
  qtyInput.focus();
  qtyInput.select();
}

function closeQtyPrompt() {
  qtyOverlay.classList.add("hidden");
  pendingAdd = null;
}

$("#qty-cancel").addEventListener("click", closeQtyPrompt);
qtyOverlay.addEventListener("click", (e) => {
  if (e.target === qtyOverlay) closeQtyPrompt();
});
qtyInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") confirmQtyPrompt();
  if (e.key === "Escape") closeQtyPrompt();
});
$("#qty-confirm").addEventListener("click", confirmQtyPrompt);

async function confirmQtyPrompt() {
  if (!pendingAdd) return;
  const quantity = Math.max(1, parseInt(qtyInput.value, 10) || 1);
  const { card, p } = pendingAdd;
  const confirmBtn = $("#qty-confirm");
  confirmBtn.disabled = true;
  confirmBtn.textContent = "Adding…";
  try {
    await addToBuylist(card, p, quantity);
    closeQtyPrompt();
  } catch (err) {
    confirmBtn.textContent = "Error";
  } finally {
    confirmBtn.disabled = false;
    confirmBtn.textContent = "Add";
  }
}

async function addToBuylist(card, p, quantity) {
  const game = gameSel.value;
  const fd = new FormData();
  fd.append("game", game);
  fd.append("card_identifier", card.identifier);
  fd.append("card_name", card.name);
  fd.append("printing_id", p.identifier);
  fd.append("printing_label", p.label);
  fd.append("quantity", String(quantity));
  if (p.set_code) fd.append("set_code", p.set_code);
  if (p.foiling) fd.append("foiling", p.foiling);
  if (p.treatment) fd.append("treatment", p.treatment);
  if (p.rarity) fd.append("rarity", p.rarity);
  if (p.image) fd.append("image_url", p.image);
  if (p.currency) fd.append("currency", p.currency);
  if (p.price_source_id) fd.append("tcgplayer_product_id", p.price_source_id);
  if (p.price_source_url) fd.append("tcgplayer_url", p.price_source_url);
  dbg("add to buylist", { card: card.name, printing: p.identifier, quantity });
  const r = await fetch("/buylist/add", { method: "POST", body: fd });
  if (!r.ok) throw new Error(r.statusText);
  await refreshBuylist();
}

// --- modal close ----------------------------------------------------------

$("#modal-close").addEventListener("click", () => modal.classList.add("hidden"));
modal.addEventListener("click", (e) => {
  if (e.target === modal) modal.classList.add("hidden");
});

// --- inline buylist (shown under the search) ------------------------------

const buylistContainer = document.querySelector("#buylist-container");

async function refreshBuylist() {
  if (!buylistContainer) return;
  try {
    const r = await fetch("/partials/buylist");
    if (r.ok) buylistContainer.innerHTML = await r.text();
  } catch (_) {
    /* leave the current markup in place on failure */
  }
}

// Delegate qty/remove form submits to fetch + refresh, so they update in
// place instead of navigating to /buylist. The listener lives on the
// container, so it keeps working after innerHTML is replaced.
if (buylistContainer) {
  buylistContainer.addEventListener("submit", async (e) => {
    const formEl = e.target;
    if (!(formEl instanceof HTMLFormElement)) return;
    // refresh-all is handled with a progress bar in buylist.js — let it bubble
    if (formEl.getAttribute("action") === "/buylist/refresh-all") return;
    e.preventDefault();
    dbg("buylist action", formEl.getAttribute("action"));
    try {
      await fetch(formEl.action, { method: "POST", body: new FormData(formEl) });
    } finally {
      await refreshBuylist();
    }
  });
}

function escapeHtml(s) {
  return String(s || "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

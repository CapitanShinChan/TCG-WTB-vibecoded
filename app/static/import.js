"use strict";

const $ = (s) => document.querySelector(s);

const gameSel = $("#game");
const textEl = $("#import-text");
const previewBtn = $("#preview-btn");
const statusEl = $("#import-status");
const previewSection = $("#preview-section");
const tableBody = $("#preview-table tbody");
const actionsEl = $("#preview-actions");
const commitResult = $("#commit-result");

let lines = []; // resolved lines from the last preview

const STATUS_LABEL = {
  matched: "matched",
  no_printing: "printing not found",
  not_found: "card not found",
  parse_error: "parse error",
};

const isMatched = (l) => l.status === "matched";

previewBtn.addEventListener("click", runPreview);

async function runPreview() {
  const text = textEl.value.trim();
  if (!text) return;
  statusEl.textContent = "Resolving… (looks up each card on the provider)";
  previewBtn.disabled = true;
  commitResult.textContent = "";
  try {
    const r = await fetch("/api/import/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ game: gameSel.value, text }),
    });
    if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
    lines = (await r.json()).lines;
    renderPreview();
  } catch (err) {
    statusEl.textContent = "Error: " + err.message;
  } finally {
    previewBtn.disabled = false;
  }
}

function renderPreview() {
  const matched = lines.filter(isMatched);
  const failed = lines.filter((l) => !isMatched(l));
  statusEl.textContent = `${lines.length} line(s), ${matched.length} matched, ${failed.length} failed`;
  previewSection.classList.remove("hidden");

  renderRows();
  renderActions(matched.length, failed.length);
}

function renderRows() {
  tableBody.innerHTML = "";
  lines.forEach((l, idx) => {
    const tr = document.createElement("tr");
    tr.className = "st-" + l.status;
    const p = l.printing;
    const altBadge = p && p.alt_art ? ` <span class="badge">alt art</span>` : "";
    const printingCell = p
      ? `${escapeHtml(p.printing_id)} ${escapeHtml(p.printing_label)}${altBadge}`
      : `<span class="placeholder">—</span>`;
    const img =
      p && p.image_url
        ? `<img class="mini" loading="lazy" src="${p.image_url}" alt="">`
        : "";
    const qtyCell = isMatched(l)
      ? `<input type="number" min="1" class="qty-input" data-idx="${idx}" value="${l.quantity}">`
      : l.quantity;

    tr.innerHTML = `
      <td class="thumb">${img}</td>
      <td class="qty-cell">${qtyCell}</td>
      <td>${escapeHtml(l.raw.trim())}</td>
      <td>${printingCell}</td>
      <td><span class="status-badge ${l.status}">${STATUS_LABEL[l.status] || l.status}</span>
          ${l.message ? `<div class="sub">${escapeHtml(l.message)}</div>` : ""}</td>
    `;
    tableBody.appendChild(tr);
  });
}

function renderActions(matchedCount, failedCount) {
  actionsEl.innerHTML = "";

  if (failedCount === 0) {
    // everything resolved — a single add action
    const add = button(`Add ${matchedCount} card(s) to buylist`, "primary");
    add.addEventListener("click", () => commitMatched(add));
    actionsEl.appendChild(add);
    return;
  }

  // some lines failed: add nothing automatically, ask what to do
  const banner = document.createElement("div");
  banner.className = "warn-banner";
  banner.innerHTML = `<strong>${failedCount} line(s) couldn't be fetched.</strong>
    Nothing has been added. Choose how to proceed:`;
  actionsEl.appendChild(banner);

  const row = document.createElement("div");
  row.className = "action-row";

  const remove = button("Remove unfetchable lines & edit", "secondary");
  remove.addEventListener("click", removeUnfetchable);

  const addAnyway = button(`Add the ${matchedCount} fetched card(s)`, "primary");
  addAnyway.disabled = matchedCount === 0;
  addAnyway.addEventListener("click", () => commitMatched(addAnyway));

  row.appendChild(remove);
  row.appendChild(addAnyway);
  actionsEl.appendChild(row);
}

function removeUnfetchable() {
  // keep only the lines that resolved, in their original text
  const kept = lines.filter(isMatched).map((l) => l.raw.trim());
  textEl.value = kept.join("\n");
  previewSection.classList.add("hidden");
  lines = [];
  commitResult.textContent = "";
  statusEl.textContent =
    "Removed unfetchable lines. Review the list and preview again.";
  textEl.focus();
}

async function commitMatched(btn) {
  const items = [];
  lines.forEach((l, idx) => {
    if (!isMatched(l)) return;
    const qtyInput = document.querySelector(`.qty-input[data-idx="${idx}"]`);
    const quantity = Math.max(1, parseInt(qtyInput.value, 10) || 1);
    items.push({
      card_identifier: l.card_identifier,
      card_name: l.card_name,
      quantity,
      printing: l.printing,
    });
  });
  if (!items.length) {
    commitResult.textContent = "Nothing to add.";
    return;
  }
  btn.disabled = true;
  commitResult.textContent = "Adding…";
  try {
    const r = await fetch("/api/import/commit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ game: gameSel.value, items }),
    });
    if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
    const { added, updated } = await r.json();
    commitResult.innerHTML = `Added ${added} new, updated ${updated}. <a href="/buylist">View buylist →</a>`;
  } catch (err) {
    commitResult.textContent = "Error: " + err.message;
    btn.disabled = false;
  }
}

function button(label, kind) {
  const b = document.createElement("button");
  b.type = "button";
  b.textContent = label;
  if (kind === "secondary") b.className = "secondary";
  return b;
}

function escapeHtml(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

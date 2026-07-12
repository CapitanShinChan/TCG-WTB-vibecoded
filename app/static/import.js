"use strict";

const $ = (s) => document.querySelector(s);

const gameSel = $("#game");
const textEl = $("#import-text");
const previewBtn = $("#preview-btn");
const statusEl = $("#import-status");
const previewSection = $("#preview-section");
const tableBody = $("#preview-table tbody");
const selectAll = $("#select-all");
const commitBtn = $("#commit-btn");
const commitResult = $("#commit-result");

let lines = []; // resolved lines from the last preview

const STATUS_LABEL = {
  matched: "matched",
  no_printing: "printing not found",
  not_found: "card not found",
  parse_error: "parse error",
};

previewBtn.addEventListener("click", async () => {
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
});

function renderPreview() {
  const matched = lines.filter((l) => l.status === "matched").length;
  statusEl.textContent = `${lines.length} line(s), ${matched} matched`;
  previewSection.classList.remove("hidden");
  tableBody.innerHTML = "";

  lines.forEach((l, idx) => {
    const tr = document.createElement("tr");
    tr.className = "st-" + l.status;
    const p = l.printing;
    const canAdd = l.status === "matched";

    const altBadge = p && p.alt_art ? ` <span class="badge">alt art</span>` : "";
    const printingCell = p
      ? `${escapeHtml(p.printing_id)} ${escapeHtml(p.printing_label)}${altBadge}`
      : `<span class="placeholder">—</span>`;

    const img = p && p.image_url
      ? `<img class="mini" loading="lazy" src="${p.image_url}" alt="">`
      : "";

    tr.innerHTML = `
      <td>${canAdd ? `<input type="checkbox" class="row-check" data-idx="${idx}" checked>` : ""}</td>
      <td class="thumb">${img}</td>
      <td class="qty-cell">${canAdd
        ? `<input type="number" min="1" class="qty-input" data-idx="${idx}" value="${l.quantity}">`
        : l.quantity}</td>
      <td>${escapeHtml(l.raw.trim())}</td>
      <td>${printingCell}</td>
      <td><span class="status-badge ${l.status}">${STATUS_LABEL[l.status] || l.status}</span>
          ${l.message ? `<div class="sub">${escapeHtml(l.message)}</div>` : ""}</td>
    `;
    tableBody.appendChild(tr);
  });
  selectAll.checked = true;
}

selectAll.addEventListener("change", () => {
  document
    .querySelectorAll(".row-check")
    .forEach((c) => (c.checked = selectAll.checked));
});

commitBtn.addEventListener("click", async () => {
  const items = [];
  document.querySelectorAll(".row-check:checked").forEach((c) => {
    const idx = +c.dataset.idx;
    const l = lines[idx];
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
    commitResult.textContent = "Nothing selected.";
    return;
  }
  commitBtn.disabled = true;
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
  } finally {
    commitBtn.disabled = false;
  }
});

function escapeHtml(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

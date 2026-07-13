"use strict";

const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));

const countEl = $("#export-count");
const discordTa = $("#discord-text");
const reimportTa = $("#reimport-text");

function buildQuery() {
  const p = new URLSearchParams();
  $$(".f-set:checked").forEach((c) => p.append("sets", c.value));
  $$(".f-foiling:checked").forEach((c) => p.append("foilings", c.value));
  const min = $("#price-min").value.trim();
  const max = $("#price-max").value.trim();
  if (min !== "") p.append("price_min", min);
  if (max !== "") p.append("price_max", max);
  return p.toString();
}

async function generate() {
  const qs = buildQuery();
  if (window.dbg) dbg("export generate", qs);
  countEl.textContent = "Generating…";
  try {
    const r = await fetch(`/api/export?${qs}`);
    if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
    const data = await r.json();
    discordTa.value = data.discord;
    reimportTa.value = data.reimport;
    countEl.textContent = `${data.count} card(s)`;
  } catch (err) {
    countEl.textContent = "Error: " + err.message;
  }
}

$("#generate-btn").addEventListener("click", generate);

// copy buttons
$$(".copy-btn").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const ta = document.getElementById(btn.dataset.target);
    try {
      await navigator.clipboard.writeText(ta.value);
      const old = btn.textContent;
      btn.textContent = "Copied ✓";
      setTimeout(() => (btn.textContent = old), 1200);
    } catch (_) {
      ta.select(); // fallback: select so the user can Ctrl+C
    }
  });
});

// download buttons — hit the download route with the current filters
$$(".dl-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    const qs = buildQuery();
    window.location = `/export/download?fmt=${btn.dataset.fmt}&${qs}`;
  });
});

// generate on load
generate();

"use strict";

// Recent-sales modal for the buylist "Suggested" price. Loaded on every page
// (via base.html), so it works on both the search page and /buylist. Uses a
// document-level delegated click so it keeps working after the inline buylist
// is re-rendered.
(function () {
  const modal = document.querySelector("#sales-modal");
  if (!modal) return;
  const titleEl = document.querySelector("#sales-modal-title");
  const bodyEl = document.querySelector("#sales-modal-body");

  function close() {
    modal.classList.add("hidden");
  }
  modal.addEventListener("click", (e) => {
    if (e.target === modal || e.target.hasAttribute("data-close-sales")) close();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") close();
  });

  document.addEventListener("click", async (e) => {
    const link = e.target.closest(".suggested-price-link");
    if (!link) return;
    e.preventDefault();
    const productId = link.dataset.productId;
    const foiling = link.dataset.foiling || "";
    if (window.dbg) dbg("fetch sales", { productId, foiling });
    titleEl.textContent = link.dataset.card || "Recent sales";
    bodyEl.innerHTML = "<p class='status'>Loading sales…</p>";
    modal.classList.remove("hidden");
    try {
      const url =
        `/api/sales/${encodeURIComponent(productId)}` +
        (foiling ? `?foiling=${encodeURIComponent(foiling)}` : "");
      const r = await fetch(url);
      if (!r.ok) throw new Error(r.statusText);
      const { currency, sales } = await r.json();
      renderSales(sales, currency);
    } catch (err) {
      bodyEl.innerHTML = `<p class='status'>Error: ${escapeHtml(err.message)}</p>`;
    }
  });

  function fmtPrice(s, currency) {
    const p =
      s.low === s.high
        ? s.low.toFixed(2)
        : `${s.low.toFixed(2)}–${s.high.toFixed(2)}`;
    return `${p} ${currency}`;
  }

  function renderSales(sales, currency) {
    if (!sales || !sales.length) {
      bodyEl.innerHTML = "<p class='status'>No recent sales found.</p>";
      return;
    }
    const rows = sales
      .map(
        (s) =>
          `<tr><td>${escapeHtml(s.date)}</td><td>${s.quantity}</td><td>${escapeHtml(
            fmtPrice(s, currency)
          )}</td></tr>`
      )
      .join("");
    bodyEl.innerHTML = `
      <table class="sales-table">
        <thead><tr><th>Date</th><th>Qty</th><th>Price</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
      <p class="status sales-note">TCGplayer aggregates sales into short date buckets; the price is that bucket's sale range.</p>`;
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }
})();

// --- progress bar over an SSE stream --------------------------------------
// Shared helper (exposed on window so import.js can use it too). POSTs a JSON
// body and reads a text/event-stream response, updating the top progress bar
// on each {type:"progress"} event. Resolves with the {type:"result"} payload.
(function () {
  const bar = document.getElementById("progress");
  const fill = document.getElementById("progress-fill");
  const label = document.getElementById("progress-label");

  function show(text) {
    if (!bar) return;
    fill.style.width = "0%";
    label.textContent = text || "";
    bar.classList.remove("hidden");
  }
  function update(done, total) {
    if (!bar) return;
    const pct = total ? Math.round((done / total) * 100) : 0;
    fill.style.width = pct + "%";
    label.textContent = `${done}/${total}`;
  }
  function hide() {
    if (bar) bar.classList.add("hidden");
  }

  window.streamProgress = async function (url, body, opts = {}) {
    show("Starting…");
    let result = null;
    try {
      const resp = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body || {}),
      });
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let sep;
        while ((sep = buf.indexOf("\n\n")) >= 0) {
          const frame = buf.slice(0, sep);
          buf = buf.slice(sep + 2);
          const dataLine = frame.split("\n").find((l) => l.startsWith("data:"));
          if (!dataLine) continue;
          const evt = JSON.parse(dataLine.slice(5).trim());
          if (evt.type === "progress") {
            update(evt.done, evt.total);
            opts.onProgress && opts.onProgress(evt);
          } else if (evt.type === "result") {
            result = evt;
          } else if (evt.type === "error") {
            opts.onError && opts.onError(evt.message);
          }
        }
      }
    } finally {
      hide();
    }
    if (result && opts.onResult) opts.onResult(result);
    return result;
  };
})();

// Refresh-all-prices with a progress bar (works on /buylist and the inline
// buylist). Intercepts the form submit and streams; reloads when done.
document.addEventListener("submit", (e) => {
  const form =
    e.target instanceof HTMLFormElement &&
    e.target.getAttribute("action") === "/buylist/refresh-all"
      ? e.target
      : null;
  if (!form) return;
  e.preventDefault();
  if (window.dbg) dbg("refresh all prices (streaming)");
  window.streamProgress("/buylist/refresh-all-stream", {}, {
    onResult: () => location.reload(),
  });
});

// --- sortable buylist table -----------------------------------------------
// Delegated on document so it works on both /buylist and the inline buylist,
// and survives the inline table being re-rendered after add/qty/remove.
(function () {
  document.addEventListener("click", (e) => {
    const th = e.target.closest("table.buylist thead th[data-col]");
    if (!th) return;
    const table = th.closest("table.buylist");
    const tbody = table.querySelector("tbody");
    const idx = Array.prototype.indexOf.call(th.parentElement.children, th);
    const numeric = th.dataset.type === "num";
    const asc = !th.classList.contains("sort-asc");

    const cellVal = (row) => {
      const cell = row.children[idx];
      return cell.dataset.sort != null ? cell.dataset.sort : cell.textContent.trim();
    };
    const rows = Array.from(tbody.querySelectorAll("tr"));
    rows.sort((a, b) => {
      let va = cellVal(a);
      let vb = cellVal(b);
      if (numeric) {
        va = parseFloat(va) || 0;
        vb = parseFloat(vb) || 0;
        return asc ? va - vb : vb - va;
      }
      return asc
        ? String(va).localeCompare(String(vb))
        : String(vb).localeCompare(String(va));
    });
    rows.forEach((r) => tbody.appendChild(r));

    table
      .querySelectorAll("thead th")
      .forEach((h) => h.classList.remove("sort-asc", "sort-desc"));
    th.classList.add(asc ? "sort-asc" : "sort-desc");
    if (window.dbg) dbg("sort buylist", { col: th.textContent.trim(), asc });
  });
})();

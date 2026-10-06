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
// body and reads a text/event-stream response, updating the modal progress UI
// on each {type:"progress"} event. Resolves with the {type:"result"} payload.
(function () {
  const bar = document.getElementById("progress");
  const fill = document.getElementById("progress-fill");
  const label = document.getElementById("progress-label");

  const track = document.getElementById("progress-track");
  const percent = document.getElementById("progress-percent");
  const title = document.getElementById("progress-title");
  const description = document.getElementById("progress-description");
  let previousFocus = null;
  bar.addEventListener("cancel", (event) => event.preventDefault());

  function show(opts) {
    previousFocus = document.activeElement;
    title.textContent = opts.title || "Updating prices";
    description.textContent = opts.description || "Fetching the latest market prices for your cards.";
    fill.style.width = "";
    label.textContent = "Connecting…";
    percent.textContent = "—";
    track.classList.add("indeterminate");
    track.removeAttribute("aria-valuenow");
    document.documentElement.classList.add("progress-open");
    bar.showModal();
    title.focus();
  }
  function update(done, total) {
    const count = Math.max(0, Number(total) || 0);
    const completed = Math.min(count, Math.max(0, Number(done) || 0));
    const pct = count ? Math.round((completed / count) * 100) : 0;
    track.classList.remove("indeterminate");
    track.setAttribute("aria-valuenow", String(pct));
    fill.style.width = pct + "%";
    percent.textContent = pct + "%";
    label.textContent = `${completed} of ${count} processed`;
  }
  function hide() {
    bar.close();
    document.documentElement.classList.remove("progress-open");
    if (previousFocus && previousFocus.isConnected && !previousFocus.disabled) previousFocus.focus();
  }

  let active = false;
  window.withProgress = async function (operation, opts = {}) {
    if (active) throw new Error("Another operation is already running.");
    active = true;
    try {
      show(opts);
      return await operation(update);
    } finally {
      active = false;
      hide();
    }
  };

  window.requireSuccess = async function (response) {
    if (response.ok) return response;
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || response.statusText || `Request failed (${response.status})`);
  };

  window.streamProgress = function (url, body, opts = {}) {
    return window.withProgress(async (updateProgress) => {
      const resp = await window.requireSuccess(await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body || {}),
      }));
      if (!resp.body) throw new Error("The server returned no progress stream.");
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      let result = null;
      try {
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          let separator;
          while ((separator = /\r?\n\r?\n/.exec(buf))) {
            const frame = buf.slice(0, separator.index);
            buf = buf.slice(separator.index + separator[0].length);
            const data = frame.split(/\r?\n/).filter(line => line.startsWith("data:"))
              .map(line => line.slice(5).trimStart()).join("\n");
            if (!data) continue;
            const evt = JSON.parse(data);
            if (evt.type === "progress") {
              updateProgress(evt.done, evt.total);
              opts.onProgress && opts.onProgress(evt);
            } else if (evt.type === "result") {
              result = evt;
            } else if (evt.type === "error") {
              throw new Error(evt.message || "The operation failed.");
            }
          }
        }
        if (!result) throw new Error("The connection ended before completion. Please try again.");
        if (opts.onResult) await opts.onResult(result);
        return result;
      } catch (error) {
        if (opts.onError) opts.onError(error.message);
        throw error;
      } finally {
        // Release an unfinished stream on parse/server errors, too.
        await reader.cancel().catch(() => {});
        reader.releaseLock();
      }
    }, opts);
  };
})();

// Shared price-refresh handling on both tables. Individual requests use an
// indeterminate dialog; bulk requests stream real per-item progress.
document.addEventListener("submit", async (e) => {
  const form = e.target;
  if (!(form instanceof HTMLFormElement)) return;
  const action = form.getAttribute("action");
  if (!["/buylist/refresh-all", "/buylist/refresh-price"].includes(action)) return;
  e.preventDefault();
  const errorEl = document.getElementById("price-refresh-error");
  errorEl.classList.add("hidden");
  const refreshView = async () => {
    if (document.querySelector("#buylist-container") && window.refreshBuylist) {
      await window.refreshBuylist();
    } else {
      location.reload();
    }
  };
  try {
    if (action === "/buylist/refresh-all") {
      await window.streamProgress("/buylist/refresh-all-stream", {}, { onResult: refreshView });
    } else {
      await window.withProgress(async () => {
        await window.requireSuccess(await fetch(action, { method: "POST", body: new FormData(form) }));
        await refreshView();
      });
    }
  } catch (error) {
    errorEl.textContent = "Price refresh failed: " + error.message;
    errorEl.classList.remove("hidden");
  }
});

// Update just the quantity cell: no navigation or table replacement, so list,
// search text, sorting, and scroll position stay exactly where the user left them.
document.addEventListener("submit", async (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement) || form.getAttribute("action") !== "/buylist/qty") return;
  event.preventDefault();
  const cell = form.closest("td.qty");
  const controls = cell.querySelector(".qty-controls");
  if (controls.dataset.pending === "true") return;
  controls.dataset.pending = "true";
  const body = new FormData(form);
  const buttons = Array.from(controls.querySelectorAll("button"));
  const focused = document.activeElement;
  const errorEl = document.getElementById("buylist-action-error");
  errorEl.classList.add("hidden");
  buttons.forEach(button => { button.disabled = true; });
  try {
    const response = await window.requireSuccess(await fetch("/buylist/qty", {
      method: "POST", headers: { "Accept": "application/json" }, body,
    }));
    const result = await response.json();
    if (!Number.isInteger(result.quantity) || result.quantity < 1 || String(result.item_id) !== body.get("item_id")) {
      throw new Error("The server returned an invalid quantity.");
    }
    controls.querySelector("span").textContent = String(result.quantity);
    cell.dataset.sort = String(result.quantity);
  } catch (error) {
    errorEl.textContent = "Quantity update failed: " + error.message;
    errorEl.classList.remove("hidden");
  } finally {
    delete controls.dataset.pending;
    buttons.forEach(button => { button.disabled = false; });
    if (buttons.includes(focused) && focused.isConnected && document.activeElement === document.body) focused.focus();
  }
});

// --- list scope switcher ---------------------------------------------------
// Delegated so it survives the inline buylist being re-rendered. On the search
// page it refreshes the inline table; elsewhere it navigates with ?scope=.
(function () {
  document.addEventListener("change", (e) => {
    const sel = e.target.closest(".buylist-scope");
    if (!sel) return;
    const scope = sel.value;
    if (window.dbg) dbg("buylist scope", scope);
    if (document.querySelector("#buylist-container") && window.refreshBuylist) {
      window.refreshBuylist();
    } else {
      const url = new URL(window.location.href);
      url.searchParams.set("scope", scope);
      window.location = url.toString();
    }
  });
})();

// Current buylist scope (used when refreshing the inline table).
window.currentBuylistScope = function () {
  const sel = document.querySelector(".buylist-scope");
  return sel ? sel.value : "all";
};

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

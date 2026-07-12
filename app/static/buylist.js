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
    titleEl.textContent = link.dataset.card || "Recent sales";
    bodyEl.innerHTML = "<p class='status'>Loading sales…</p>";
    modal.classList.remove("hidden");
    try {
      const r = await fetch(`/api/sales/${encodeURIComponent(productId)}`);
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

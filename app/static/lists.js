"use strict";

// Delete prompt for a list: the user chooses whether the list's cards move to
// General or get deleted with it.
(function () {
  const overlay = document.getElementById("delete-overlay");
  if (!overlay) return;
  const label = document.getElementById("delete-label");
  const hint = document.getElementById("delete-hint");
  const idField = document.getElementById("delete-list-id");
  const modeField = document.getElementById("delete-mode");

  function close() {
    overlay.classList.add("hidden");
  }

  document.querySelectorAll(".delete-list").forEach((btn) => {
    btn.addEventListener("click", () => {
      const count = Number(btn.dataset.count || 0);
      idField.value = btn.dataset.listId;
      modeField.value = "move";
      label.textContent = `Delete list "${btn.dataset.listName}"?`;
      hint.textContent = count
        ? `It holds ${count} card(s). Choose whether to keep them (they move to General) or delete them too.`
        : "The list is empty.";
      overlay.classList.remove("hidden");
      if (window.dbg) dbg("delete list prompt", btn.dataset.listName);
    });
  });

  // the two submit buttons set the mode before the form posts
  document.getElementById("delete-move").addEventListener("click", () => {
    modeField.value = "move";
  });
  document.getElementById("delete-all").addEventListener("click", () => {
    modeField.value = "delete";
  });

  document.getElementById("delete-cancel").addEventListener("click", close);
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) close();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") close();
  });
})();

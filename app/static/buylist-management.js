"use strict";

// Named-list controls are delegated so refreshed inline tables keep working.
(function () {
  const dialog = document.getElementById("buylist-editor");
  if (!dialog) return;
  const form = document.getElementById("buylist-editor-form");
  const id = document.getElementById("buylist-editor-id");
  const name = document.getElementById("buylist-editor-name");
  const nameField = document.getElementById("buylist-name-field");
  const title = document.getElementById("buylist-editor-title");
  const description = document.getElementById("buylist-delete-description");
  const save = document.getElementById("buylist-editor-save");
  let deleting = false;
  const error = document.getElementById("buylist-editor-error");
  const cancel = document.getElementById("buylist-editor-cancel");
  let saving = false;

  function close() {
    if (!saving) dialog.close();
  }
  cancel.addEventListener("click", close);
  dialog.addEventListener("cancel", event => {
    if (saving) event.preventDefault();
  });
  dialog.addEventListener("close", () => document.documentElement.classList.remove("list-dialog-open"));

  document.addEventListener("click", event => {
    const trigger = event.target.closest("[data-edit-buylist], [data-delete-buylist]");
    if (!trigger || dialog.open) return;
    id.value = trigger.dataset.listId;
    name.value = trigger.dataset.listName;
    deleting = trigger.hasAttribute("data-delete-buylist");
    name.required = !deleting;
    nameField.classList.toggle("hidden", deleting);
    description.classList.toggle("hidden", !deleting);
    document.getElementById("buylist-delete-name").textContent = name.value;
    title.textContent = deleting ? "Delete buylist" : "Edit buylist";
    save.textContent = deleting ? "Delete buylist and cards" : "Save changes";
    save.className = deleting ? "remove" : "list-save";
    error.classList.add("hidden");
    document.documentElement.classList.add("list-dialog-open");
    dialog.showModal();
    if (deleting) {
      cancel.focus(); // Never focus the destructive confirmation by default.
    } else {
      name.focus();
      name.select();
    }
  });

  async function showRemainingLists() {
    const url = new URL(location.href);
    url.searchParams.set("scope", "all");
    const container = document.getElementById("buylist-container");
    if (!container) {
      location.assign(url.toString());
      return;
    }
    history.replaceState(null, "", url);
    // Deletion already committed: do not leave deleted cards actionable, even
    // if fetching the remaining lists fails. Never offer a second delete here.
    container.replaceChildren();
    try {
      const response = await window.requireSuccess(await fetch("/partials/buylist?scope=all"));
      container.innerHTML = await response.text();
    } catch (_) {
      const message = document.createElement("p");
      message.className = "status";
      message.textContent = "Buylist deleted. Reload this page to see your remaining lists.";
      container.appendChild(message);
    }
  }

  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (saving) return;
    name.value = name.value.trim();
    if (!deleting && !name.value) {
      error.textContent = "Enter a buylist name.";
      error.classList.remove("hidden");
      name.focus();
      return;
    }
    const body = new URLSearchParams(new FormData(form));
    if (deleting) {
      body.delete("name");
      body.set("mode", "delete");
    }
    const submittedId = body.get("list_id");
    const submittedName = body.get("name");
    saving = true;
    const buttons = Array.from(form.querySelectorAll("button, input"));
    buttons.forEach(button => { button.disabled = true; });
    error.classList.add("hidden");
    try {
      const endpoint = deleting ? "/lists/delete" : "/lists/rename";
      await window.requireSuccess(await fetch(endpoint, { method: "POST", body }));
      if (deleting) {
        const destination = document.getElementById("qty-list");
        if (destination) {
          if (destination.value === submittedId) destination.value = "general";
          Array.from(destination.options).forEach(option => {
            if (option.value === submittedId) option.remove();
          });
        }
        dialog.close();
        await showRemainingLists();
      } else {
        document.querySelectorAll(".buylist-scope option, #qty-list option").forEach(option => {
          if (option.value === submittedId) option.textContent = submittedName;
        });
        document.querySelectorAll("[data-edit-buylist], [data-delete-buylist]").forEach(trigger => {
          if (trigger.dataset.listId === submittedId) trigger.dataset.listName = submittedName;
        });
        dialog.close();
      }
    } catch (failure) {
      error.textContent = failure.message;
      error.classList.remove("hidden");
    } finally {
      saving = false;
      buttons.forEach(button => { button.disabled = false; });
    }
  });
})();

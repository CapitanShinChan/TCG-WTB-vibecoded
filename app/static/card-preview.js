"use strict";

// Delegation keeps previews working after the inline buylist is replaced/sorted.
(function () {
  const dialog = document.querySelector("#card-preview");
  if (!dialog) return;
  const image = dialog.querySelector("#card-preview-image");
  const title = dialog.querySelector("#card-preview-title");

  document.addEventListener("click", (event) => {
    const trigger = event.target.closest(".card-preview-trigger");
    if (!trigger || !trigger.dataset.image) return;
    image.src = trigger.dataset.image;
    image.alt = trigger.dataset.cardName;
    title.textContent = trigger.dataset.cardName;
    dialog.showModal();
    document.documentElement.classList.add("card-preview-open");
  });

  dialog.querySelector(".card-preview-close").addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  });
  // Escape and focus restoration are provided by the native dialog.
  dialog.addEventListener("close", () => {
    document.documentElement.classList.remove("card-preview-open");
    image.removeAttribute("src");
  });
})();

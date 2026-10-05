"use strict";

// Inspect local cache health without initiating a provider download.
window.refreshCatalogueStatus = async function () {
  const banner = document.getElementById("catalogue-warning");
  if (!banner) return;
  try {
    const response = await fetch("/api/catalogue-status");
    if (!response.ok) return;
    const status = await response.json();
    let message = "";
    if (status.available && status.stale) {
      message = `Using cached catalogue ${status.version}; freshness could not be confirmed. New cards or corrected printings may be missing. Updates retry on subsequent lookups.`;
    } else if (status.available && status.persistent === false) {
      message = "The catalogue is loaded in memory but could not be saved. Check cache-directory permissions and disk space; restarting offline may make search unavailable.";
    } else if (!status.available && status.error) {
      message = "Card catalogue unavailable. Check the connection and retry your search shortly.";
    }
    banner.textContent = message;
    banner.classList.toggle("hidden", !message);
  } catch (_) {
    // Keep an existing warning visible if the app itself cannot be reached.
  }
};
window.refreshCatalogueStatus();

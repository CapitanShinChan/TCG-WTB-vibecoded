"use strict";

// Lightweight console debug logger, gated on window.APP_DEBUG (injected by the
// server from the APP_DEBUG env var). Set APP_DEBUG=0 in production to silence
// every dbg(...) call across the app.
window.dbg = function () {
  if (!window.APP_DEBUG) return;
  console.log(
    "%c[card-inv]",
    "color:#2e7de0;font-weight:bold",
    ...arguments
  );
};

# Changelog

Human-readable changes to Card Inventory. Keep new work under **Unreleased**;
when releasing, move it into a dated/versioned section. Describe observable
behavior, compatibility implications, and important trade-offs—not individual
commits. This document starts with the local-catalogue change; earlier history
has not been reconstructed.

## Unreleased

### Export asking prices and GEM wrapper-color emojis

- Show an exactly-zero suggested price as `0.5$` per card in the Discord export
  and its text download. Leave missing values and every nonzero price unchanged;
  this is not a blanket $0.50 floor. Re-importable lists remain price-free.
- Keep the adjustment in the renderer only: no saved prices/history, quantities,
  pricing ceilings or metadata are rewritten. Price filters still use the saved
  suggested/current values, not the adjusted export asking price.
- Replace generic GEM boxes with distinct wrapper-color markers: 🔴 GEM1,
  🔵 GEM2, 🔴🔵 GEM3, ⚪ GEM4, 🔵🟣 GEM5 and 🟣 GEM6. Paired dots reflect actual
  two-color wrappers; GEM4 is pearl/ivory, and GEM6's wrapper is dark purple rather
  than the promotional image's green glow. Official artwork sources are linked
  in the README. Unknown/unmapped sets and other-game groups keep 📦.
- Verification: 85 Python tests (including isolated API/download and full-row
  nonmutation checks), the Node test and whitespace checks passed. Both behavior
  changes were observed failing before implementation. Independent review passed
  with no security concerns or logic errors; its isolated probe also verified
  negative-price handling and preservation of populated price-history fields.
  No live database changes, app startup or price-provider requests were made.
- Restart the running app and regenerate the export; no price refresh is needed.
  Changes remain uncommitted.

### Export GEM filters, suggested-price ceiling, and Escape dismissal

- Resolve export sets from FaB printing IDs rather than trusting legacy stored
  GEM labels. The checkbox list, API filtering, Discord grouping and downloads
  share the same resolution; no metadata migration or catalogue fetch is needed.
  Show GEM1–GEM6 whenever recognized GEM cards exist, including empty packs.
  Unknown codes and other games retain their original labels.
- Cap the final suggested price at the newest valid sale-bucket midpoint and
  current market price **after** rounding, so rounding cannot undo either ceiling.
  Retain existing SKU selection, latest-100 weighting and trimmed-mean behavior.
  TCGplayer supplies aggregated buckets rather than an individual last-sale value;
  use the available side when one sale-price bound is missing. No sales means no
  suggestion. Saved prices adopt the calculation on their next refresh.
- Escape dismisses the topmost add-card overlay from any focused control. Close
  quantity/destination first, then printings on the next Escape. Do not submit a
  card or dismiss an underlying add overlay while a native dialog is open.
  A late add response cannot close a reopened prompt; Escape cannot undo an add
  request already sent to the server.
- Verification: all 78 Python tests, 27 offline Edge browser tests, the Node test,
  JavaScript syntax and whitespace checks passed. Read-only verification against
  the actual database found 72 stored generic-GEM entries and confirmed six export
  options; those entries resolve to GEM1–GEM5, with GEM6 currently empty. No live
  inventory or saved pricing was modified. Independent review passed with no
  security concerns, logic errors, or suggestions.
- Restart the app and refresh the page to load the Python/JavaScript changes;
  refresh prices to update existing suggestions. Changes remain uncommitted.

### GEM1–GEM6 set labels

- Split generic GEM metadata into the correct GEM1–GEM6 pack based on the printed
  card code, using verified, explicit pack ranges rather than equal-sized ranges.
- Use the corrected labels in search, printing choices, imported/new buylist
  entries, table views and export grouping/filtering. Printing identities and
  foiling/art variants are unchanged.
- Correct existing FaB rows at startup, changing only set metadata and a matching
  GEM prefix in the display label. The operation is repeatable and offline;
  quantities, lists, pricing snapshots/history, images and product references
  are preserved. Other games and unknown/future IDs are left alone.
- Retain the local FaBrary catalogue; the official CardDB APIs were used to verify
  pack assignments, not introduced as a per-request dependency. Source fixtures
  document paired GEM1 IDs and the GEM219/Minerva Themis omission in those APIs.
- Verification: all 371 GEM variants in the cached catalogue mapped to the six
  packs with their identities preserved. All 58 Python tests, 22 offline browser
  tests, the Node test and whitespace checks passed. Independent review passed
  with no blocking findings.
- The live inventory database was not opened or migrated during this work.
  Restart the app to run the metadata correction; changes remain uncommitted.

### Compact price-trend tooltips

- Replace the full list of prices/timestamps with three lines: data-point count,
  percentage change, and the latest recorded observation date in `yyyy/mm/dd`.
- Use the high of the displayed history for downward trends and the low for
  upward trends (not local turning points). Percentages show two decimals;
  unchanged net prices show 0%. The date uses the stored UTC observation time.
- Show N/A when a percentage cannot be calculated (including one observation or
  a zero baseline), and Unknown for an absent/invalid observation date.
- Remove individual point tooltips so they no longer override the concise graph
  summary. Graph geometry, colors, recorded prices, and storage are unchanged.
- Verification: 51 Python tests, 22 offline browser tests, the Node test and
  whitespace checks passed. Independent review passed with no blocking findings.
  Existing uncommitted UI changes were preserved; no live database access,
  restart or commit.

### Edit and delete from the buylist view

- Add Edit buylist and Delete buylist beside the selected named list in both
  standalone and inline buylist views, including empty named lists. All and
  General are protected views rather than deletable named lists; Manage lists
  remains available for the full list-management page.
- Edit the name in a native dialog without leaving the current view. Duplicate
  or blank names show validation errors; in-flight saves freeze submitted fields.
- Require explicit confirmation before deleting a named buylist and all its card
  entries. The dialog names the target, warns that deletion is permanent, and
  initially focuses Cancel. It uses the existing explicit full-delete mode, not
  the keep-cards/move-to-General mode. Other lists and General are unaffected.
- After deletion, show All in the same page section. Inline deletion preserves
  search text; if refreshing the view fails, deleted entries are removed from
  the UI and a reload message is shown rather than another delete action.
- Keep the Add-to-buylist destination menu synchronized after inline rename and
  deletion. A deleted selected destination resets to General before any table
  reload, including the table-refresh failure path; other selections are kept.
- Verification after that correction: all 46 Python tests, 22 offline browser
  tests, the Node test, syntax and whitespace checks passed. Tests exercise real
  list endpoints with an isolated database and subsequent Add request payloads.
  Independent re-review passed with no blocking findings. No live list or
  inventory data was changed.

### Trend colors and stable quantity edits

- Price-trend lines are green for a net drop, red for a net rise, and blue for
  no net change across the displayed history. A single observation is blue.
- Fix quantity +/- controls leaving the selected view. They now request the saved
  quantity as JSON and update only that cell on both standalone and inline
  buylists. The URL, chosen list, search text, row order and sort selection stay
  unchanged. Pending edits disable both controls for that row; failures retain
  the displayed value, show an error, and re-enable the controls.
- Normal HTML quantity submissions also retain the selected list via an encoded
  scope parameter instead of redirecting to the unscoped buylist. Quantities
  still cannot drop below one; missing rows return an explicit 404.
- Verification: all 43 Python tests, 14 offline browser tests, the Node test,
  JavaScript syntax and whitespace checks passed. Coverage includes All,
  General, and a named list alongside a separate Dani list, on both table views;
  it also checks errors, duplicate submissions, and exact trend colors.
  Independent review passed with no blocking findings.
- No database schema changes, live inventory access, restart, commit, or push.
  Restart the app to load the backend quantity-response change, then refresh
  the browser to pick up the updated templates and scripts.

### Centered loading overlay

- Replace the thin top progress strip with a centered green loading dialog,
  rounded panel, animated refresh icon, progress percentage and processed count.
  The background is dimmed, desaturated and blurred while loading.
- Use a native modal dialog to block mouse and keyboard interaction outside it.
  Escape/backdrop clicks cannot dismiss an active operation; background scrolling
  is locked. Completion or failure closes the dialog and restores interaction.
- Apply the overlay to both single-card and bulk price refreshes in standalone
  and inline buylist views. Before a total is known, show an indeterminate bar
  rather than invented progress. Inline tables refresh without a full navigation.
- Keep import preview on the shared progress UI with import-specific wording.
  Respect reduced-motion preferences and fit mobile/landscape viewports.
- Reject duplicate progress operations. Surface refresh errors instead of silently
  treating HTTP errors, malformed streams or early disconnects as completion.
- Verification: seven new offline loading-dialog browser tests and five existing
  browser tests passed in installed Microsoft Edge; all 38 Python tests, the Node
  test, JavaScript syntax checks and `git diff --check` passed. Independent review
  passed with no blocking findings. Screenshot inspected for centering, green
  styling and dimmed app.
- No backend, price calculation, database or dependency changes. No server restart,
  live inventory access, commit or push was performed for this UI change.

### Recorded price history and table graphs

- Store up to ten current-market price observations per buylist entry, including
  time and currency. All price-refresh routes participate; an existing saved
  price is retained when history starts, without inventing an unknown timestamp.
- Add a tiny SVG History column between Current and Suggested in the shared
  buylist table. Handles empty, single-point, flat, rising and falling histories;
  includes price/date tooltips and accessible text. Client-side price sorting
  and partial table replacement continue to work; no chart dependency is added.
- Add a nullable JSON column through the existing additive startup migration.
  Existing inventory rows are preserved. Restart and refresh prices to populate
  history; no historical prices are fabricated or downloaded to fill ten slots.
- Preserve combined history during legacy-ID reconciliation and moves into
  General, retaining the newest ten observations in the selected currency.
  Reuse the whole-snapshot selection policy during list merges so the surviving
  current/suggested prices remain consistent with the retained history.
- Ignore missing price observations; reject non-finite/negative current prices
  before changing the saved snapshot. Currency changes do not mix units.
- Serialize refresh writes with SQLite's transaction lock and reload the latest
  saved snapshot before appending, so overlapping refresh requests retain both
  observations. Network fetching precedes the lock. Both bulk routes commit
  per item; completed items stay saved if a later item fails.
- Verification after the concurrency correction: 38 Python tests, one Node test,
  five offline browser tests, and `git diff --check` passed. Tests cover two
  stale sessions, overlapping HTTP refreshes on all three routes, rollback,
  latest-ten retention, and bulk transaction boundaries. Browser checks used
  installed Microsoft Edge (Chromium). Independent re-review passed with no
  blocking findings; the original concurrent-refresh observation loss is fixed.
- The user's live database was not opened or migrated during verification;
  the running server was not restarted. Histories are observations on refresh,
  not a scheduled daily series; graph points are evenly spaced and individually
  scaled. The startup upgrade runs when the app is next started.

### Enlarged card previews

- Card thumbnails and names in buylist tables now open a larger image centered
  on the screen, including named-list views and the search page's inline list.
- Preview uses the saved printing's image, fits desktop/mobile viewports without
  distortion, and closes via Escape, the close button, or clicking outside.
- Native modal dialog provides keyboard focus containment/restoration. Background
  scrolling is locked while open; cards without an image remain plain text.
- Delegated events continue working after inline table replacement and sorting.
- Added four offline Chromium browser tests using real templates/assets and
  synthetic card images; documented the test-only Playwright setup in README.
- Verification: all four browser tests, 23 existing Python tests, the existing
  Node test, JavaScript syntax validation, and `git diff --check` passed.
- No backend/database behavior changed; the user's inventory was not modified.

### 2026-09-23 — Local FaBrary catalogue

#### Summary and reason

Replaced remote GraphQL card lookup with a persistent JSON catalogue and local
search. FaBrary's `searchCards` GraphQL operation had been removed, causing the
app's search endpoint to return HTTP 502. Its printing schema also changed from
`treatment` to a `treatments` array, and the old shared printing identifier no
longer safely distinguished foil variants.

A JSON file was chosen over additional SQLite tables or a NoSQL service: the
application consumes complete upstream snapshots and needs straightforward name
search and card lookup. The existing buylist remains in SQLite.

#### Added

- Version discovery through FaBrary's `app-info.json` and download of the
  corresponding `cards-<version>.json` catalogue.
- Persistent cache at `.cache/fabrary-catalogue.json`, excluded from Git.
  `APP_CATALOGUE_CACHE` can override the cache file path.
- Validation before accepting a downloaded or saved catalogue, including card
  and variant IDs, treatment arrays, and fields consumed by adapters/search.
- Atomic file replacement: incomplete or invalid updates cannot overwrite the
  last good snapshot.
- `/api/catalogue-status` and UI warnings for stale data, unavailable catalogues,
  and failures to persist an otherwise usable in-memory catalogue.
- Automated coverage for caching, offline fallback, concurrent access, provider
  adaptation, HTTP routes, imports, legacy IDs, and catalogue-warning display.
  Test dependencies and commands are documented in `requirements-dev.txt` and
  the README.

#### Changed

- Card search now runs against the in-memory catalogue: literal,
  case-insensitive name substrings, exact matches first, card backs excluded.
  Card details and printings come from the same catalogue snapshot.
- Version checks occur on the first lookup after one hour. The full catalogue
  is downloaded again only when its upstream version changes.
- Failed refreshes keep the previous catalogue available and retry on the first
  lookup after 60 seconds. A cold network failure remains an explicit provider
  error, not an empty search result.
- A successful download remains usable in memory if disk persistence fails;
  the app reports that limitation and retries saving on a subsequent check.
- Only one thread refreshes at a time. The request performing the refresh waits,
  while other requests can read the previous snapshot and status without
  waiting for network I/O.
- New printing IDs use `fab:<print>`, preserving FaBrary's complete variant key
  and avoiding collisions with legacy foil/non-foil IDs.
- Treatment arrays are stored as JSON in the existing text field. Existing
  single-label values remain readable; no database schema migration is needed.
- Affected legacy IDs are reconciled transactionally when adding a card or
  moving a list into General. Matching uses saved metadata and requires one
  unambiguous variant. Ambiguous or missing matches stop the operation with
  HTTP 409 rather than silently selecting a different printing.

#### Fixed

- Broken card search and printing lookup after FaBrary's API changes.
- Foil/non-foil variants sharing one inventory identity.
- Extended Art import/export detection for printings with multiple treatments.
- Repeated copies of one printing within a single import batch now merge before
  commit instead of creating competing pending rows.
- Search-page additions now surface the server's error message rather than
  discarding the explanation.
- Duplicate legacy-ID reconciliation preserves saved pricing instead of losing
  it when the surviving canonical row is unpriced. It retains one complete
  pricing snapshot: priced beats unpriced, then newer known timestamps win;
  ties or two unknown timestamps keep the canonical snapshot. Missing compatible
  TCGplayer references are retained without overwriting existing references.
- Compatibility tests now enforce the same General-bucket partial unique index
  as the production SQLite database.

#### Removed

- Cognito credentials, AWS request signing, and GraphQL calls from card lookup.
- The `boto3` runtime dependency. Existing environments need not uninstall it.

#### Unchanged and operational notes

- Buylist data remains in `inventory.db`; this implementation work did not modify
  the user's existing database. No startup migration rewrites inventory IDs.
- TCGplayer still supplies prices. Images still load from FaBrary's CDN: the
  catalogue cache does not make those features available offline.
- Restart an already-running server to load the code changes. The first lookup
  needs connectivity unless a valid cache already exists.
- This targets the existing single-worker local app. Multiple processes can
  download redundantly and temporarily hold different catalogue versions.
- Advanced FaBrary search syntax is not supported. Text export still does not
  preserve exact set/edition/variant identity on re-import.
- The upstream integration is unofficial; cached data can become stale, and
  future schema changes may require another adapter update.

#### Verification

- Live-data route checks returned HTTP 200 for `doomsaying` and `doom`, with one
  and seven results respectively. These were in-process HTTP checks, not a
  restart of the user's running server.
- The adapter processed all 5,177 cards and 17,371 distinct variant IDs in the
  inspected catalogue. Normal and Rainbow Foil Doomsaying imported separately.
- A fresh-process lookup succeeded from the saved catalogue with network calls
  disabled.
- A read-only audit mapped all 34 existing buylist rows unambiguously, including
  entries whose upstream image URLs had changed.
- The pricing-loss issue found during review has been corrected and verified
  with regression tests, including timestamp conflicts and missing references.
- Final local checks passed: 23 Python tests, the JavaScript warning-display
  test, and `git diff --check`. Python tests use in-memory databases; the user's
  existing `inventory.db` was not modified. The running server was not restarted.

#### Code map

- `app/fabrary/client.py`: catalogue download, validation, persistence, lookup.
- `app/fabrary/compat.py`: legacy printing-ID reconciliation.
- `app/providers/flesh_and_blood.py`: catalogue-to-provider adaptation.
- `app/treatments.py`, `app/importer.py`, `app/export.py`: multi-treatment support.
- `app/main.py`: catalogue status and buylist integration.
- `app/static/catalogue.js`, page scripts, `app/templates/base.html`: warnings
  and error presentation.
- `tests/`: regression coverage, isolated from the user's inventory database.

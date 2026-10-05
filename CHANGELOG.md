# Changelog

Human-readable changes to Card Inventory. Keep new work under **Unreleased**;
when releasing, move it into a dated/versioned section. Describe observable
behavior, compatibility implications, and important trade-offs—not individual
commits. This document starts with the local-catalogue change; earlier history
has not been reconstructed.

## Unreleased

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

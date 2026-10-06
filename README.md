# Card Inventory

Local web app to track trading-card buylists across games and check
current prices. Game-agnostic core with pluggable per-game providers.

See [CHANGELOG.md](CHANGELOG.md) for changes, compatibility notes, and verification status.

Currently supported:

- **Flesh and Blood** — local card search + printings from a cached copy of
  [FaBrary](https://fabrary.net)'s versioned JSON catalogue.

Pricing comes from TCGplayer's (unofficial) Infinite price-history API, keyed by
the TCGplayer product id captured on each printing:

- **Current** — most recent market price listed on TCGplayer.
- **Suggested** — trimmed mean of recent sales for the Near Mint / English SKU:
  each sale bucket's midpoint price is weighted by quantity sold (latest 100
  weighted points); if there are 10+ points, the highest 25% are discarded before
  averaging. After the usual market cap and .00/.50 rounding, the final value is
  capped at both the newest valid sale-bucket price and the current market price.
  A cap may therefore produce a value outside .00/.50. The API supplies aggregated
  buckets, not individual transactions: "latest sale" means the newest valid
  bucket's low/high midpoint, or its available price when one side is missing.
  Missing sales do not create a suggested price. Refresh saved prices after
  restarting to apply the updated calculation; old snapshots are not rewritten.

Refresh a single item (↻) or all items ("Refresh all prices") from the buylist.
A centered green progress dialog dims the app and blocks background mouse,
keyboard and scrolling while the request runs. Bulk updates show a processed
count and percentage; individual updates show an indeterminate animation.
The dialog closes on completion or failure, and errors appear in the page.
Import preview uses the same dialog with card-matching text. Reduced-motion
preferences are respected.

## Setup

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Windows
# source .venv/bin/activate && pip install -r requirements.txt  # macOS/Linux
```

## Run

```bash
.venv/Scripts/python run.py
```

Then open http://127.0.0.1:8000

- **Search**: pick a game, type a card name, browse results (images preloaded
  from the provider). Click a card to see every printing, then "Add to buylist".
  Escape closes the quantity/destination prompt from any focused control; another
  Escape closes the printing picker. Closing a prompt does not undo an add request
  already submitted. Native dialogs keep their own Escape behavior, including the
  noncancelable progress dialog.
- **Import**: paste a card list and add many at once. Format is one card per
  line, `Nx [CODES] Name`, e.g. `3x Tempestuous Kiss` or
  `1x CF EA Flowstate Embodiment`. Codes: `RF` Rainbow Foil, `CF` Cold Foil,
  `MV` Marvel, `NF` Non Foil (standard), `EA` Extended Art. Each line is
  validated against the provider (exact name + matching printing); a preview
  shows what matched before you add the selected rows.
- **Buylist**: view/adjust quantities, remove items, and refresh prices. A list
  selector switches between **All**, **General** (cards not in any list) and
  each named list. Quantity +/- buttons update in place without reloading or
  changing the selected view, search text, row order, or sort selection.
  Select a named list to reveal **Edit buylist** (rename without leaving the
  view) and **Delete buylist**. Deletion asks for confirmation, removes the
  selected list and all its entries, and then shows All. Other lists and General
  are not affected. All/General themselves cannot be renamed or deleted.
  The Add-to-buylist destination menu updates with renames and deletions; if its
  selected list is deleted, the destination returns to General.
- **Lists**: group cards into named lists (e.g. one per deck) on the Lists page
  — create empty, rename, delete. The same printing can live in several lists,
  each with its own quantity. Deleting a list asks whether to keep its cards
  (moved to General) or delete them too. Adding from Search, and Import, let
  you pick the target list (default General); Export can be scoped to one list
  (default All).
- **Export**: filter the buylist (by set, printing/foiling, suggested-price
  range) and export either a Discord "WTB" message (grouped by set, with
  suggested prices) or a re-importable `.txt` list. Copy to clipboard or
  download. In the Discord message and its `.txt` download, an exactly-zero
  suggested price is shown as `0.5$` per card. Missing and nonzero prices are
  unchanged (this is not a minimum-price rule). This is an export-only asking
  price: saved suggestions, price history, the pricing algorithm and price-range
  filters are unchanged. Re-importable lists still omit prices and emojis.

## Price history

Each buylist entry keeps its latest **10 recorded current-market prices** in
SQLite, with the observation time and currency. Single-item refresh, Refresh
all, and streamed refresh all record observations. Repeated equal prices still
count; failed refreshes and missing prices do not invent points. The first
refresh preserves an existing saved price as the oldest point (an unknown old
timestamp stays unknown). This is refresh history, **not** a backfill of
TCGplayer's historical sale buckets and not an automatic daily tracker.

A tiny SVG **History** graph appears between Current and Suggested on both
buylist views, including named lists and the search page's inline table. Points
run oldest-to-newest left-to-right, evenly spaced by observation rather than
elapsed time. Each graph uses its own vertical scale. Its tooltip shows only the
point count, percentage change, and latest observation date (`yyyy/mm/dd`, UTC).
Downward trends compare with the highest displayed price; upward trends compare
with the lowest. No net change shows 0%; a single point or undefined percentage
shows N/A, and a missing date shows Unknown. Rising prices are red,
falling prices green, and unchanged prices blue; a single observation is a blue dot.
Color reflects the net change from the first to the last displayed observation.
Unrecorded histories show a dash. No chart library or extra API request is used.

Restart the app to add the nullable `price_history` JSON column automatically;
the upgrade preserves existing rows and is safe to repeat. Refresh prices after
restarting to begin filling the graphs. List merges and legacy-ID reconciliation
combine histories, remove duplicate dated observations, and retain the newest ten.
Different currencies are never mixed on a graph; a new-currency refresh starts
that currency's history. Deleting an item also deletes its history.

Overlapping refresh writes are serialized using SQLite's transaction lock; the
latest saved snapshot is reloaded under that lock before appending history.
Provider fetching happens first. SQLite serializes all database writes, so other
writes can briefly wait. Both bulk refresh routes commit each item separately,
releasing the lock before the next provider call; completed items remain saved
if a later item fails.

## GEM pack labels

GEM printings are labeled by their actual pack, rather than one generic GEM set.
The same labels are used by search results, printing choices, imports, buylist
rows, and export filters/grouping. Printed card IDs and variant identities are
not changed: for example, GEM141 belongs to GEM5 but stays GEM141.

Export resolves the pack directly from each FaB printing ID, so old rows still
stored as generic GEM are filtered and grouped correctly without requiring a
metadata migration first. When recognized GEM cards are present, the export
page offers all six GEM1–GEM6 checkboxes, including packs with no saved cards.
Selecting an empty pack produces no cards; unknown GEM codes keep their existing
set label instead of being assigned to a pack by guesswork. Other games are not
reclassified. Restart a running app to load changed Python export code.

Discord export headers use wrapper-color emojis, visually matched to the official
pack images below. Two-color packs use paired dots rather than an invented single
color; these are approximate Unicode colors, not official color names:

- 🔴 GEM1 — deep red ([wrapper](https://cdn.fabtcg.com/uploads/2025/06/Gem_packs.png)).
- 🔵 GEM2 — teal/blue ([wrapper](https://cdn.fabtcg.com/uploads/2025/07/25_05_GEMPACK_2_CAROUSEL3.jpg)).
- 🔴🔵 GEM3 — red and blue/indigo ([wrapper](https://cdn.fabtcg.com/uploads/2025/12/GEMPACK_3_PACKS-1.png)).
- ⚪ GEM4 — pearl/ivory ([wrapper](https://cdn.fabtcg.com/uploads/2026/01/GEM-PACK-4-PACKS-1-scaled.png)).
- 🔵🟣 GEM5 — cyan and purple ([wrapper](https://cdn.fabtcg.com/uploads/2026/05/GEM-PACK-5-PACKS_-scaled.png)).
- 🟣 GEM6 — dark purple ([official artwork with wrappers](https://cdn.fabtcg.com/uploads/2026/09/gem-pack-6-cover-1024x768.png)); the surrounding green glow is not the wrapper color.

Pack 1–5 images are listed in the [official Armory assets](https://fabtcg.com/digital-assets/armory-events/);
pack 6 artwork is linked from the [official announcement](https://fabtcg.com/articles/gem-pack-6/).
Other sets, unknown generic GEM groups and other-game groups retain 📦. Exporting
uses this local mapping; it does not download artwork or call a provider.

- [GEM1](https://api.cardvault.fabtcg.com/carddb/api/v1/product-cards/gem-pack-1/): `GEM001`–`GEM032`.
- [GEM2](https://api.cardvault.fabtcg.com/carddb/api/v1/product-cards/gem-pack-2/): `GEM033`–`GEM068`.
- [GEM3](https://api.cardvault.fabtcg.com/carddb/api/v1/product-cards/gem-pack-3/): `GEM069`–`GEM104`.
- [GEM4](https://api.cardvault.fabtcg.com/carddb/api/v1/product-cards/gem-pack-4/): `GEM105`–`GEM140`.
- [GEM5](https://api.cardvault.fabtcg.com/carddb/api/v1/product-cards/gem-pack-5/): `GEM141`–`GEM183`.
- [GEM6](https://api.cardvault.fabtcg.com/carddb/api/v1/product-cards/gem-pack-6/): `GEM184`–`GEM219`.

The assignments were checked against the official CardDB product endpoints
above and saved as a small offline mapping. There are no new network requests
on startup or lookup. The current endpoints omit four paired GEM1 weapon codes
(GEM002/004/006/009), which are explicitly assigned by the
[official promo register](https://fabtcg.com/collectors-centre/promos-and-extras/).
The GEM6 endpoint currently stops at GEM218; GEM219 is Minerva Themis in the
FaBrary catalogue, corroborated as GEM6 by
[this report](https://afabjourney.substack.com/p/just-two-armories-this-week).
The [official GEM6 announcement](https://fabtcg.com/articles/gem-pack-6/)
describes a 36-card set. Source-backed code lists and these exceptions are
recorded in `tests/fixtures/gem_pack_codes.json`.

Restart the app once to correct existing FaB GEM `set_code` values and matching
GEM prefixes in their display labels. This is an idempotent metadata-only update:
quantities, list membership, IDs, images, TCGplayer references and complete price
history stay untouched. New additions and stale import/add payloads are normalized
too. Unknown, malformed or future card codes are left unchanged rather than guessed;
new GEM packs require an explicit verified mapping update.

## Architecture

```
app/
  main.py              FastAPI routes (pages + JSON API + buylist mutations)
  db.py, models.py     SQLite via SQLAlchemy (BuylistItem)
  importer.py          parse pasted card lists + resolve lines to printings
  providers/
    base.py            GameProvider ABC + CardResult / Printing dataclasses
    registry.py        game_id -> provider registry (drives the UI selector)
    flesh_and_blood.py FaB provider backed by FaBrary
  pricing/tcgplayer.py TCGplayer Infinite price-history fetch + suggested-price calc
  fabrary/client.py    version discovery, validated disk cache, local search/lookup
  fabrary/compat.py    safe legacy printing-ID reconciliation on buylist writes
  treatments.py       treatment-array encoding + legacy scalar compatibility
  templates/, static/  Jinja2 pages + vanilla JS/CSS frontend
```

Adding a game later: implement a `GameProvider` and register it in
`providers/registry.py`.

## Authentication

The whole app is behind single-user HTTP Basic auth (`app/auth.py`). The
password is a salted PBKDF2-SHA256 hash, never plaintext. Credentials load with
this precedence:

1. **Production** — env vars `AUTH_USERNAME`, `AUTH_SALT`, `AUTH_PASSWORD_HASH`.
2. **Local testing** — a git-ignored `auth_local.json` at the project root
   (copy `auth_local.example.json`).
3. Neither configured → auth fails closed.

Basic auth sends credentials every request, so serve only over HTTPS.

**Brute-force protection** (in-memory, per source IP): every failed attempt is
delayed; after 5 failures an IP is locked out with exponential backoff (HTTP
429 + `Retry-After`, capped at 5 min); a success or 15 min idle resets it.
Requests with no credentials aren't penalised (browsers probe once before
prompting).

## Logging & debug

Every HTTP request (incoming to the app, and outgoing to FaBrary / TCGplayer)
is logged to two files under `logs/`:

- `access.log` — one compact human-readable line per request.
- `http.jsonl` — one ECS-schema JSON object per line, for ingestion into a log
  aggregator (Loki, Elastic, Splunk, Datadog).

The frontend also prints `[card-inv]` debug messages to the browser console.
Both the console messages and the debug flag are controlled by the `APP_DEBUG`
env var (default on); set `APP_DEBUG=0` in production to silence the console
(file logs still write). `APP_LOG_DIR` overrides the log directory.

## Local card catalogue

Card lookups no longer use GraphQL, Cognito, or AWS credentials. The client reads
`https://content.fabrary.net/info/app-info.json` and its `latestCardsVersion`,
then downloads `https://content.fabrary.net/info/cards-<version>.json`.

- The first lookup downloads and validates the catalogue. Later searches are
  literal case-insensitive name substring matches, with exact matches first;
  card backs are excluded. FaBrary's advanced search syntax is not supported.
- The complete snapshot is saved to `.cache/fabrary-catalogue.json` (git-ignored).
  `APP_CATALOGUE_CACHE` overrides the **file path**. Its parent must be writable.
- Each process loads the disk cache once and indexes cards by identifier in
  memory. Version checks happen on the first lookup after one hour, not via a
  background scheduler. Only a changed version downloads the catalogue again.
- A validated snapshot replaces the previous file atomically. Failed downloads
  or invalid schemas keep the last good catalogue usable. If saving fails, a
  valid download is still served from memory, with a persistence warning; the
  previous disk file is left intact. Failed checks/saves retry on the first
  lookup after 60 seconds. An empty-cache network failure returns a provider
  error rather than fabricated or empty results.
- `/api/catalogue-status` exposes the loaded version and refresh state. Search
  and Import show a warning when using a catalogue whose freshness cannot be
  confirmed, or when the loaded snapshot could not be saved. Refresh failures
  are also logged to the server console.
- The cache stores metadata, **not images or prices**. Images still use FaBrary's
  CDN, and price refreshes still call TCGplayer. These need connectivity.
- This targets the existing single-process local app. Threads share one refresh
  lock. The request performing a refresh waits for the network; other requests
  can read the previous in-memory snapshot and status without waiting. Separate
  worker processes can perform redundant downloads and maintain
  different in-memory versions until their next check. Use one worker here.

### Existing buylist compatibility

New printing IDs are `fab:<print>`: the complete FaBrary variant key, not its
shared card/set identifier. Foilings, editions, and treatments stay distinct.
The prefix prevents new non-foil IDs from colliding with old foil entries.

There is no startup migration of printing IDs; the GEM correction above only
updates set metadata. When adding a card or moving a list's
cards into General, affected legacy rows are reconciled inside that operation's
transaction. Matching uses the saved ID, foiling, treatments, image and (when
available) TCGplayer product reference. A renamed image alone does not establish
a match. Ambiguous/missing matches stop the operation with HTTP 409; no guessing.
ID reconciliation preserves quantities and retains one complete pricing snapshot
when duplicate legacy/canonical rows merge. A priced snapshot beats an unpriced
one; otherwise the newer known timestamp wins. Known timestamps beat unknown
ones, and ties retain the canonical row's snapshot. Current/suggested prices,
sample size, timestamp, and currency are kept together. Ordinary viewing,
quantity changes, removal, and pricing do not require ID reconciliation.

Treatment arrays are stored losslessly as JSON in the existing `treatment` text
field; old scalar labels still work. Import/export EA checks use membership,
so a printing with both Alternate Art and Extended Art keeps its EA code.
The text export format still does not encode an exact set/edition/variant ID;
re-import selects a matching printing, not necessarily the identical one.

This remains an unofficial integration; upstream schema changes can require an
adapter update. A cached snapshot is a fallback, not a guarantee of fresh data.

## Tests

```bash
.venv/Scripts/python -m pip install -r requirements-dev.txt
.venv/Scripts/python -B -m unittest discover -s tests -v
node --test tests/catalogue_status.test.cjs
```

Python tests use synthetic CDN fixtures, temporary cache files, and in-memory
SQLite databases; they do not run app startup or modify `inventory.db`. Set
`CARD_INVENTORY_TEST_TMP` to an existing directory to control test scratch paths.
Node's built-in test runner checks the catalogue-warning UI without dependencies.

Browser regression tests exercise the real templates and JavaScript with synthetic
card images and intercepted requests (no running server, database, or live API needed):

```bash
.venv/Scripts/python -m playwright install chromium
.venv/Scripts/python -B tests/card_preview_browser.py
.venv/Scripts/python -B tests/loading_overlay_browser.py
.venv/Scripts/python -B tests/buylist_management_browser.py
.venv/Scripts/python -B tests/add_card_modal_browser.py
```

`PLAYWRIGHT_CHROMIUM_EXECUTABLE` optionally selects an existing Chromium executable.
The tests cover image/name previews, dismissal and keyboard focus, refreshed/sorted
inline tables, and mobile/landscape sizing.

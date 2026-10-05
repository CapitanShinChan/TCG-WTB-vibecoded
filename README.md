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
  each sale bucket's midpoint price is weighted by quantity sold; if there are
  10+ sale points, the highest 25% are discarded before averaging.

Refresh a single item (↻) or all items ("Refresh all prices") from the buylist.

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
- **Import**: paste a card list and add many at once. Format is one card per
  line, `Nx [CODES] Name`, e.g. `3x Tempestuous Kiss` or
  `1x CF EA Flowstate Embodiment`. Codes: `RF` Rainbow Foil, `CF` Cold Foil,
  `MV` Marvel, `NF` Non Foil (standard), `EA` Extended Art. Each line is
  validated against the provider (exact name + matching printing); a preview
  shows what matched before you add the selected rows.
- **Buylist**: view/adjust quantities, remove items, and refresh prices. A list
  selector switches between **All**, **General** (cards not in any list) and
  each named list.
- **Lists**: group cards into named lists (e.g. one per deck) on the Lists page
  — create empty, rename, delete. The same printing can live in several lists,
  each with its own quantity. Deleting a list asks whether to keep its cards
  (moved to General) or delete them too. Adding from Search, and Import, let
  you pick the target list (default General); Export can be scoped to one list
  (default All).
- **Export**: filter the buylist (by set, printing/foiling, suggested-price
  range) and export either a Discord "WTB" message (grouped by set, with
  suggested prices) or a re-importable `.txt` list. Copy to clipboard or
  download.

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
elapsed time. Each graph uses its own vertical scale. Hover a point for its
price/date; screen-reader text exposes the observations. Rising prices are red,
falling prices green, and flat prices grey; a single observation is a dot.
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

There is no startup database migration. When adding a card or moving a list's
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
```

`PLAYWRIGHT_CHROMIUM_EXECUTABLE` optionally selects an existing Chromium executable.
The tests cover image/name previews, dismissal and keyboard focus, refreshed/sorted
inline tables, and mobile/landscape sizing.

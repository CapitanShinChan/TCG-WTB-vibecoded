# Card Inventory

Local web app to track trading-card inventory across games and (later) check
current prices. Game-agnostic core with pluggable per-game providers.

Currently supported:

- **Flesh and Blood** — card search + all printings via [FaBrary](https://fabrary.net)'s
  AppSync GraphQL API.

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
- **Buylist**: view/adjust quantities, remove items, and refresh prices.
- **Export**: filter the buylist (by set, printing/foiling, suggested-price
  range) and export either a Discord "WTB" message (grouped by set, with
  suggested prices) or a re-importable `.txt` list. Copy to clipboard or
  download.

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
  fabrary/client.py    Cognito unauth creds + SigV4 AppSync GraphQL client
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

Every HTTP request (incoming to the app, and outgoing to FaBrary / TCGplayer /
Cognito) is logged to two files under `logs/`:

- `access.log` — one compact human-readable line per request.
- `http.jsonl` — one ECS-schema JSON object per line, for ingestion into a log
  aggregator (Loki, Elastic, Splunk, Datadog).

The frontend also prints `[card-inv]` debug messages to the browser console.
Both the console messages and the debug flag are controlled by the `APP_DEBUG`
env var (default on); set `APP_DEBUG=0` in production to silence the console
(file logs still write). `APP_LOG_DIR` overrides the log directory.

## Notes

FaBrary's API is behind AWS AppSync (IAM auth via a Cognito identity pool) and
AWS WAF. The client mints anonymous credentials and SigV4-signs requests. This
is an unofficial integration and may break if FaBrary changes their backend.

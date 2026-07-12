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
- **Buylist**: view/adjust quantities and remove items. Prices show as
  placeholders until price lookup is implemented.

## Architecture

```
app/
  main.py              FastAPI routes (pages + JSON API + buylist mutations)
  db.py, models.py     SQLite via SQLAlchemy (BuylistItem)
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

## Notes

FaBrary's API is behind AWS AppSync (IAM auth via a Cognito identity pool) and
AWS WAF. The client mints anonymous credentials and SigV4-signs requests. This
is an unofficial integration and may break if FaBrary changes their backend.

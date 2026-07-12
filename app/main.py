"""FastAPI app: game selector, card search, and buylist."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_session, init_db
from .fabrary.client import FabraryError
from .models import BuylistItem
from .pricing.tcgplayer import TCGPlayerError, get_pricing
from .providers import registry

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(title="Card Inventory")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.on_event("startup")
def _startup() -> None:
    init_db()


def _load_buylist(db: Session) -> list[BuylistItem]:
    """Buylist items, most recently added first."""
    return list(
        db.scalars(select(BuylistItem).order_by(BuylistItem.created_at.desc())).all()
    )


# --- pages -----------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_session)):
    return templates.TemplateResponse(
        request,
        "index.html",
        {"games": registry.all_games(), "items": _load_buylist(db)},
    )


@app.get("/buylist", response_class=HTMLResponse)
def buylist(request: Request, db: Session = Depends(get_session)):
    return templates.TemplateResponse(
        request,
        "buylist.html",
        {"items": _load_buylist(db), "games": registry.all_games()},
    )


@app.get("/partials/buylist", response_class=HTMLResponse)
def buylist_partial(request: Request, db: Session = Depends(get_session)):
    """Just the buylist table fragment, for live refresh on the search page."""
    return templates.TemplateResponse(
        request, "_buylist_table.html", {"items": _load_buylist(db)}
    )


# --- json api (used by the search UI) --------------------------------------

@app.get("/api/search")
def api_search(game: str, q: str):
    provider = registry.get_provider(game)
    if not provider:
        raise HTTPException(404, f"Unknown game: {game}")
    if not q.strip():
        return {"results": []}
    try:
        results = provider.search(q)
    except FabraryError as e:
        raise HTTPException(502, f"Card provider error: {e}")
    return {"results": [r.__dict__ for r in results]}


@app.get("/api/printings")
def api_printings(game: str, id: str):
    provider = registry.get_provider(game)
    if not provider:
        raise HTTPException(404, f"Unknown game: {game}")
    try:
        printings = provider.printings(id)
    except FabraryError as e:
        raise HTTPException(502, f"Card provider error: {e}")
    return {
        "printings": [{**p.__dict__, "label": p.label} for p in printings]
    }


# --- buylist mutations -----------------------------------------------------

@app.post("/buylist/add")
def buylist_add(
    game: str = Form(...),
    card_identifier: str = Form(...),
    card_name: str = Form(...),
    printing_id: str = Form(...),
    printing_label: str = Form(...),
    set_code: str | None = Form(None),
    foiling: str | None = Form(None),
    treatment: str | None = Form(None),
    rarity: str | None = Form(None),
    image_url: str | None = Form(None),
    currency: str | None = Form(None),
    tcgplayer_product_id: str | None = Form(None),
    tcgplayer_url: str | None = Form(None),
    db: Session = Depends(get_session),
):
    existing = db.scalar(
        select(BuylistItem).where(
            BuylistItem.game == game, BuylistItem.printing_id == printing_id
        )
    )
    if existing:
        existing.quantity += 1
    else:
        db.add(
            BuylistItem(
                game=game,
                card_identifier=card_identifier,
                card_name=card_name,
                printing_id=printing_id,
                printing_label=printing_label,
                set_code=set_code,
                foiling=foiling,
                treatment=treatment,
                rarity=rarity,
                image_url=image_url,
                quantity=1,
                price=None,  # placeholder
                currency=currency,
                tcgplayer_product_id=tcgplayer_product_id,
                tcgplayer_url=tcgplayer_url,
            )
        )
    db.commit()
    return JSONResponse({"ok": True})


@app.post("/buylist/remove")
def buylist_remove(item_id: int = Form(...), db: Session = Depends(get_session)):
    item = db.get(BuylistItem, item_id)
    if item:
        db.delete(item)
        db.commit()
    return RedirectResponse("/buylist", status_code=303)


@app.post("/buylist/qty")
def buylist_qty(
    item_id: int = Form(...), delta: int = Form(...), db: Session = Depends(get_session)
):
    item = db.get(BuylistItem, item_id)
    if item:
        item.quantity = max(1, item.quantity + delta)
        db.commit()
    return RedirectResponse("/buylist", status_code=303)


# --- pricing ---------------------------------------------------------------

def _refresh_price(item: BuylistItem) -> bool:
    """Fetch TCGplayer pricing for one item and update it. Returns success."""
    if not item.tcgplayer_product_id:
        return False
    result = get_pricing(item.tcgplayer_product_id)
    item.price = result.current_price
    item.suggested_price = result.suggested_price
    item.price_sample_size = result.sample_size
    item.currency = result.currency
    item.price_updated_at = dt.datetime.now(dt.timezone.utc)
    return True


@app.post("/buylist/refresh-price")
def buylist_refresh_price(
    item_id: int = Form(...), db: Session = Depends(get_session)
):
    item = db.get(BuylistItem, item_id)
    if item:
        try:
            _refresh_price(item)
            db.commit()
        except TCGPlayerError as e:
            raise HTTPException(502, f"TCGplayer error: {e}")
    return RedirectResponse("/buylist", status_code=303)


@app.post("/buylist/refresh-all")
def buylist_refresh_all(db: Session = Depends(get_session)):
    items = db.scalars(
        select(BuylistItem).where(BuylistItem.tcgplayer_product_id.is_not(None))
    ).all()
    for item in items:
        try:
            _refresh_price(item)
        except TCGPlayerError:
            continue  # skip items that fail; keep going
    db.commit()
    return RedirectResponse("/buylist", status_code=303)

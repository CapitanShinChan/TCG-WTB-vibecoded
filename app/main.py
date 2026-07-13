"""FastAPI app: game selector, card search, and buylist."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_session, init_db
from .fabrary.client import FabraryError
from .importer import parse_list, resolve_list
from .models import BuylistItem
from .pricing.tcgplayer import (
    CURRENCY,
    TCGPlayerError,
    get_pricing,
    get_sales,
    variant_for_foiling,
)
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


# --- list import -----------------------------------------------------------

@app.get("/import", response_class=HTMLResponse)
def import_page(request: Request):
    return templates.TemplateResponse(
        request, "import.html", {"games": registry.all_games()}
    )


class ImportPreviewReq(BaseModel):
    game: str
    text: str


class ImportCommitItem(BaseModel):
    card_identifier: str
    card_name: str
    quantity: int
    printing: dict


class ImportCommitReq(BaseModel):
    game: str
    items: list[ImportCommitItem]


@app.post("/api/import/preview")
def api_import_preview(req: ImportPreviewReq):
    provider = registry.get_provider(req.game)
    if not provider:
        raise HTTPException(404, f"Unknown game: {req.game}")
    try:
        resolved = resolve_list(parse_list(req.text), provider)
    except FabraryError as e:
        raise HTTPException(502, f"Card provider error: {e}")
    return {"lines": [r.as_dict() for r in resolved]}


@app.post("/api/import/commit")
def api_import_commit(req: ImportCommitReq, db: Session = Depends(get_session)):
    added = updated = 0
    for item in req.items:
        p = item.printing
        created = _upsert_buylist_item(
            db,
            game=req.game,
            card_identifier=item.card_identifier,
            card_name=item.card_name,
            printing_id=p.get("printing_id"),
            printing_label=p.get("printing_label"),
            set_code=p.get("set_code"),
            foiling=p.get("foiling"),
            treatment=p.get("treatment"),
            rarity=p.get("rarity"),
            image_url=p.get("image_url"),
            currency=p.get("currency"),
            tcgplayer_product_id=p.get("tcgplayer_product_id"),
            tcgplayer_url=p.get("tcgplayer_url"),
            quantity=max(1, item.quantity),
        )
        added += 1 if created else 0
        updated += 0 if created else 1
    db.commit()
    return {"added": added, "updated": updated}


# --- buylist mutations -----------------------------------------------------

def _upsert_buylist_item(
    db: Session,
    *,
    game: str,
    card_identifier: str,
    card_name: str,
    printing_id: str,
    printing_label: str,
    set_code: str | None = None,
    foiling: str | None = None,
    treatment: str | None = None,
    rarity: str | None = None,
    image_url: str | None = None,
    currency: str | None = None,
    tcgplayer_product_id: str | None = None,
    tcgplayer_url: str | None = None,
    quantity: int = 1,
) -> bool:
    """Add a printing to the buylist or bump its quantity. Returns True if a new
    row was created, False if an existing row was incremented."""
    existing = db.scalar(
        select(BuylistItem).where(
            BuylistItem.game == game, BuylistItem.printing_id == printing_id
        )
    )
    if existing:
        existing.quantity += quantity
        return False
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
            quantity=quantity,
            price=None,
            currency=currency,
            tcgplayer_product_id=tcgplayer_product_id,
            tcgplayer_url=tcgplayer_url,
        )
    )
    return True


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
    _upsert_buylist_item(
        db,
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
        currency=currency,
        tcgplayer_product_id=tcgplayer_product_id,
        tcgplayer_url=tcgplayer_url,
        quantity=1,
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
    result = get_pricing(
        item.tcgplayer_product_id, variant_for_foiling(item.foiling)
    )
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


@app.get("/api/sales/{product_id}")
def api_sales(product_id: str, foiling: str | None = None):
    """Recent sales for a TCGplayer product (feeds the suggested-price modal).
    `foiling` selects the same SKU/variant used for the suggested price."""
    try:
        sales = get_sales(product_id, variant_for_foiling(foiling))
    except TCGPlayerError as e:
        raise HTTPException(502, f"TCGplayer error: {e}")
    return {"currency": CURRENCY, "sales": [s.__dict__ for s in sales]}


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

"""FastAPI app: game selector, card search, and buylist."""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import time
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import export
from .auth import (
    FAILURE_DELAY,
    is_authorized,
    record_failure,
    record_success,
    seconds_blocked,
)
from .config import DEBUG
from .db import SessionLocal, get_session, init_db
from .fabrary.client import FabraryError
from .importer import parse_list, resolve_iter, resolve_list
from .logging_setup import log_http, setup_logging
from .models import BuylistItem, CardList
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
# exposed to every template so the frontend can gate console debug messages
templates.env.globals["app_debug"] = DEBUG
# printing-code display (NF/CF/RF/EA) used by the buylist table
templates.env.filters["printing_code"] = export.display_printing

app = FastAPI(title="Card Inventory")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.on_event("startup")
def _startup() -> None:
    setup_logging()
    init_db()


_AUTH_CHALLENGE = {"WWW-Authenticate": 'Basic realm="Card Inventory"'}


def _client_ip(request: Request) -> str:
    # behind a proxy (e.g. Azure App Service) the real IP is in X-Forwarded-For
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@app.middleware("http")
async def _require_auth(request: Request, call_next):
    ip = _client_ip(request)

    blocked = seconds_blocked(ip)
    if blocked > 0:  # locked out — reject without even checking credentials
        return Response(
            status_code=429,
            headers={**_AUTH_CHALLENGE, "Retry-After": str(int(blocked) + 1)},
        )

    auth_header = request.headers.get("Authorization")
    if is_authorized(auth_header):
        record_success(ip)
        return await call_next(request)

    # Only penalise an actual wrong attempt (credentials were presented). A
    # browser's first credential-less request just gets the challenge.
    if auth_header:
        record_failure(ip)
        await asyncio.sleep(FAILURE_DELAY)
    return Response(status_code=401, headers=_AUTH_CHALLENGE)


@app.middleware("http")
async def _access_log(request: Request, call_next):
    # static assets would just be noise
    if request.url.path.startswith("/static"):
        return await call_next(request)
    start = time.perf_counter()
    response = await call_next(request)
    log_http(
        direction="local",
        method=request.method,
        url=str(request.url),
        path=request.url.path,
        params=dict(request.query_params),
        status=response.status_code,
        duration_ms=(time.perf_counter() - start) * 1000,
    )
    return response


# Defined last so it is the OUTERMOST middleware: it must post-process every
# response, including the 401/429 that the auth middleware short-circuits.
@app.middleware("http")
async def _security_headers(request: Request, call_next):
    response = await call_next(request)
    # don't advertise the underlying technology
    response.headers["Server"] = "web"
    for leaky in ("X-Powered-By", "X-AspNet-Version", "X-Runtime"):
        if leaky in response.headers:
            del response.headers[leaky]
    # hardening headers (non-identifying)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


# Server-Sent Events helpers (progress streaming)
_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj)}\n\n"


# --- card lists ------------------------------------------------------------
# A "scope" selects which items to show/export:
#   "all"      -> every item (default)
#   "general"  -> only unlisted items (list_id IS NULL)
#   "<id>"     -> only items in that list
SCOPE_ALL = "all"
SCOPE_GENERAL = "general"


def _all_lists(db: Session) -> list[CardList]:
    return list(db.scalars(select(CardList).order_by(CardList.name)).all())


def _target_list_id(value: str | None) -> int | None:
    """Where a card should be *written*. General/blank -> None (unlisted)."""
    if not value or value in (SCOPE_GENERAL, SCOPE_ALL):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _load_buylist(db: Session, scope: str | None = SCOPE_ALL) -> list[BuylistItem]:
    """Buylist items for a scope, most recently added first."""
    stmt = select(BuylistItem).order_by(BuylistItem.created_at.desc())
    if scope and scope != SCOPE_ALL:
        if scope == SCOPE_GENERAL:
            stmt = stmt.where(BuylistItem.list_id.is_(None))
        else:
            try:
                stmt = stmt.where(BuylistItem.list_id == int(scope))
            except (TypeError, ValueError):
                pass  # unknown scope -> treat as "all"
    return list(db.scalars(stmt).all())


# --- pages -----------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    scope: str = SCOPE_ALL,
    db: Session = Depends(get_session),
):
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "games": registry.all_games(),
            "items": _load_buylist(db, scope),
            "lists": _all_lists(db),
            "scope": scope,
        },
    )


@app.get("/buylist", response_class=HTMLResponse)
def buylist(
    request: Request,
    scope: str = SCOPE_ALL,
    db: Session = Depends(get_session),
):
    return templates.TemplateResponse(
        request,
        "buylist.html",
        {
            "items": _load_buylist(db, scope),
            "games": registry.all_games(),
            "lists": _all_lists(db),
            "scope": scope,
        },
    )


@app.get("/partials/buylist", response_class=HTMLResponse)
def buylist_partial(
    request: Request,
    scope: str = SCOPE_ALL,
    db: Session = Depends(get_session),
):
    """Just the buylist table fragment, for live refresh on the search page."""
    return templates.TemplateResponse(
        request,
        "_buylist_table.html",
        {"items": _load_buylist(db, scope), "lists": _all_lists(db), "scope": scope},
    )


# --- list management -------------------------------------------------------

@app.get("/lists", response_class=HTMLResponse)
def lists_page(request: Request, db: Session = Depends(get_session)):
    lists = _all_lists(db)
    counts = {
        lst.id: db.scalar(
            select(func.count(BuylistItem.id)).where(BuylistItem.list_id == lst.id)
        )
        for lst in lists
    }
    general_count = db.scalar(
        select(func.count(BuylistItem.id)).where(BuylistItem.list_id.is_(None))
    )
    return templates.TemplateResponse(
        request,
        "lists.html",
        {"lists": lists, "counts": counts, "general_count": general_count},
    )


@app.post("/lists/create")
def lists_create(name: str = Form(...), db: Session = Depends(get_session)):
    name = name.strip()
    if not name:
        raise HTTPException(400, "List name required")
    if db.scalar(select(CardList).where(CardList.name == name)):
        raise HTTPException(409, f"A list named {name!r} already exists")
    db.add(CardList(name=name))
    db.commit()
    return RedirectResponse("/lists", status_code=303)


@app.post("/lists/rename")
def lists_rename(
    list_id: int = Form(...), name: str = Form(...), db: Session = Depends(get_session)
):
    name = name.strip()
    if not name:
        raise HTTPException(400, "List name required")
    lst = db.get(CardList, list_id)
    if not lst:
        raise HTTPException(404, "List not found")
    clash = db.scalar(select(CardList).where(CardList.name == name))
    if clash and clash.id != list_id:
        raise HTTPException(409, f"A list named {name!r} already exists")
    lst.name = name
    db.commit()
    return RedirectResponse("/lists", status_code=303)


@app.post("/lists/delete")
def lists_delete(
    list_id: int = Form(...),
    mode: str = Form("move"),  # "move" cards to General, or "delete" them
    db: Session = Depends(get_session),
):
    lst = db.get(CardList, list_id)
    if not lst:
        raise HTTPException(404, "List not found")
    items = db.scalars(
        select(BuylistItem).where(BuylistItem.list_id == list_id)
    ).all()
    for item in items:
        if mode == "delete":
            db.delete(item)
        else:
            # move to General, merging with an existing unlisted row if any
            existing = db.scalar(
                select(BuylistItem).where(
                    BuylistItem.game == item.game,
                    BuylistItem.printing_id == item.printing_id,
                    BuylistItem.list_id.is_(None),
                )
            )
            if existing:
                existing.quantity += item.quantity
                db.delete(item)
            else:
                item.list_id = None
    db.delete(lst)
    db.commit()
    return RedirectResponse("/lists", status_code=303)


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


# --- export (Discord + .txt) -----------------------------------------------

_STANDARD_LABEL = "Standard"  # UI label for a non-foil (foiling is None)


def _export_filter_options(items) -> tuple[list[str], list[str]]:
    sets = sorted(
        {export.set_of(it) for it in items},
        key=lambda s: (s == "Others", s.lower()),
    )
    foilings = sorted({it.foiling or _STANDARD_LABEL for it in items})
    return sets, foilings


def _apply_export_filters(items, sets, foilings, price_min, price_max):
    set_filter = set(sets) if sets else None
    foiling_filter = None
    if foilings:
        # map the UI "Standard" label back to a None foiling
        foiling_filter = {None if f == _STANDARD_LABEL else f for f in foilings}
    return export.filter_items(
        items,
        sets=set_filter,
        foilings=foiling_filter,
        price_min=price_min,
        price_max=price_max,
    )


@app.get("/export", response_class=HTMLResponse)
def export_page(request: Request, db: Session = Depends(get_session)):
    sets, foilings = _export_filter_options(_load_buylist(db))
    return templates.TemplateResponse(
        request,
        "export.html",
        {
            "games": registry.all_games(),
            "sets": sets,
            "foilings": foilings,
            "lists": _all_lists(db),
        },
    )


@app.get("/api/export")
def api_export(
    db: Session = Depends(get_session),
    sets: list[str] | None = Query(None),
    foilings: list[str] | None = Query(None),
    price_min: float | None = None,
    price_max: float | None = None,
    scope: str = SCOPE_ALL,
):
    items = _apply_export_filters(
        _load_buylist(db, scope), sets, foilings, price_min, price_max
    )
    return {
        "count": len(items),
        "discord": export.discord_text(items),
        "reimport": export.reimport_text(items),
    }


@app.get("/export/download")
def export_download(
    fmt: str = "discord",
    db: Session = Depends(get_session),
    sets: list[str] | None = Query(None),
    foilings: list[str] | None = Query(None),
    price_min: float | None = None,
    price_max: float | None = None,
    scope: str = SCOPE_ALL,
):
    items = _apply_export_filters(
        _load_buylist(db, scope), sets, foilings, price_min, price_max
    )
    if fmt == "reimport":
        body, filename = export.reimport_text(items), "buylist.txt"
    else:
        body, filename = export.discord_text(items), "buylist_discord.txt"
    return PlainTextResponse(
        body,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --- list import -----------------------------------------------------------

@app.get("/import", response_class=HTMLResponse)
def import_page(request: Request, db: Session = Depends(get_session)):
    return templates.TemplateResponse(
        request,
        "import.html",
        {"games": registry.all_games(), "lists": _all_lists(db)},
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
    target_list: str | None = None  # None/"general" -> unlisted


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


@app.post("/api/import/preview-stream")
def api_import_preview_stream(req: ImportPreviewReq):
    """Same as /api/import/preview but streams per-line progress via SSE."""
    provider = registry.get_provider(req.game)
    if not provider:
        raise HTTPException(404, f"Unknown game: {req.game}")
    parsed = parse_list(req.text)

    def gen():
        total = len(parsed)
        yield _sse({"type": "progress", "done": 0, "total": total})
        results = []
        try:
            for i, resolved in enumerate(resolve_iter(parsed, provider)):
                results.append(resolved.as_dict())
                yield _sse({"type": "progress", "done": i + 1, "total": total})
        except FabraryError as e:
            yield _sse({"type": "error", "message": f"Card provider error: {e}"})
            return
        yield _sse({"type": "result", "lines": results})

    return StreamingResponse(
        gen(), media_type="text/event-stream", headers=_SSE_HEADERS
    )


@app.post("/api/import/commit")
def api_import_commit(req: ImportCommitReq, db: Session = Depends(get_session)):
    added = updated = 0
    target_list = _target_list_id(req.target_list)
    for item in req.items:
        p = item.printing
        created = _upsert_buylist_item(
            db,
            list_id=target_list,
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
    list_id: int | None = None,
) -> bool:
    """Add a printing to a list (None = General) or bump its quantity there.
    Returns True if a new row was created, False if an existing one was bumped.
    The same printing may exist in several lists, each with its own quantity."""
    existing = db.scalar(
        select(BuylistItem).where(
            BuylistItem.game == game,
            BuylistItem.printing_id == printing_id,
            BuylistItem.list_id.is_(None)
            if list_id is None
            else BuylistItem.list_id == list_id,
        )
    )
    if existing:
        existing.quantity += quantity
        return False
    db.add(
        BuylistItem(
            game=game,
            list_id=list_id,
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
    quantity: int = Form(1),
    target_list: str | None = Form(None),
    db: Session = Depends(get_session),
):
    _upsert_buylist_item(
        db,
        list_id=_target_list_id(target_list),
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
        quantity=max(1, quantity),
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


@app.post("/buylist/refresh-all-stream")
def buylist_refresh_all_stream():
    """Refresh every priced item, streaming per-item progress via SSE."""
    def gen():
        db = SessionLocal()
        try:
            items = db.scalars(
                select(BuylistItem).where(
                    BuylistItem.tcgplayer_product_id.is_not(None)
                )
            ).all()
            total = len(items)
            yield _sse({"type": "progress", "done": 0, "total": total})
            for i, item in enumerate(items):
                try:
                    _refresh_price(item)
                    db.commit()
                except TCGPlayerError:
                    db.rollback()
                yield _sse({"type": "progress", "done": i + 1, "total": total})
            yield _sse({"type": "result", "refreshed": total})
        finally:
            db.close()

    return StreamingResponse(
        gen(), media_type="text/event-stream", headers=_SSE_HEADERS
    )

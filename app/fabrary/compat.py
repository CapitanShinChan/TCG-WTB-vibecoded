"""Reconcile old FaBrary IDs on writes, without a startup/data migration."""
from __future__ import annotations

from sqlalchemy import select

from .client import card_image_url, client
from ..models import BuylistItem
from ..pricing.history import merge_pricing
from ..treatments import treatment_names


class PrintingConflict(ValueError):
    """A saved printing cannot be mapped unambiguously to the catalogue."""


def canonical_printing_id(card: dict | None, printing_id: str, *, foiling=None,
                          image_url=None, treatment=None, tcgplayer_product_id=None) -> str:
    if not card:
        raise PrintingConflict("Card is absent from the current catalogue; existing data was not changed")
    printings = card["printings"]
    if printing_id.startswith("fab:"):
        matches = [p for p in printings if f"fab:{p['print']}" == printing_id
                   and (p.get("foiling") or None) == (foiling or None)]
    else:
        matches = [p for p in printings if p["identifier"] == printing_id
                   and (p.get("foiling") or None) == (foiling or None)]
        if tcgplayer_product_id:
            matches = [p for p in matches if str((p.get("tcgplayer") or {}).get("productId"))
                       == str(tcgplayer_product_id)]
        if image_url:
            image_matches = [p for p in matches if card_image_url(p.get("image")) == image_url]
            # FaBrary renamed foil image keys. A changed URL is acceptable only
            # with a matching product reference and exactly one remaining variant.
            if image_matches or not tcgplayer_product_id:
                matches = image_matches
        old_treatments = set(treatment_names(treatment))
        if old_treatments:
            matches = [p for p in matches if old_treatments <= set(p.get("treatments") or [])]
    if len(matches) != 1:
        raise PrintingConflict(
            f"Printing {printing_id!r} has {len(matches)} catalogue matches. "
            "Review its saved foiling/art/edition before adding or moving this card."
        )
    return f"fab:{matches[0]['print']}"


def reconcile_items(db, card_identifier: str, list_id: int | None, *, card=None) -> None:
    """Canonicalize a card's legacy rows in one list. Caller owns transaction.

    Resolve every row first; ambiguity aborts before changing any of them.
    Duplicate quantities are summed. Keep one whole pricing snapshot: priced
    beats unpriced, then newer known timestamps win; ties keep the target.
    """
    rows = db.scalars(select(BuylistItem).where(
        BuylistItem.game == "flesh-and-blood",
        BuylistItem.card_identifier == card_identifier,
        BuylistItem.list_id.is_(None) if list_id is None else BuylistItem.list_id == list_id,
    )).all()
    legacy = [r for r in rows if not r.printing_id.startswith("fab:")]
    if not legacy:
        return
    if card is None:
        card = client.get_card(card_identifier)
    resolved = [(r, canonical_printing_id(card, r.printing_id, foiling=r.foiling,
                 image_url=r.image_url, treatment=r.treatment,
                 tcgplayer_product_id=r.tcgplayer_product_id)) for r in legacy]
    by_id = {r.printing_id: r for r in rows if r not in legacy}
    for row, canonical in resolved:
        target = by_id.get(canonical)
        if target:
            target.quantity += row.quantity
            merge_pricing(target, row)
            if not target.tcgplayer_product_id:
                target.tcgplayer_product_id = row.tcgplayer_product_id
            if not target.tcgplayer_url and (
                not row.tcgplayer_product_id
                or target.tcgplayer_product_id == row.tcgplayer_product_id
            ):
                target.tcgplayer_url = row.tcgplayer_url
            db.delete(row)
        else:
            row.printing_id = canonical
            by_id[canonical] = row
    db.flush()

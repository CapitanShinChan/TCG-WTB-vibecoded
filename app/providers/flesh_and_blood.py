"""Flesh and Blood provider backed by the local FaBrary catalogue."""
from __future__ import annotations

from ..fabrary.client import card_image_url
from ..fabrary.client import client as fabrary
from .base import CardResult, GameProvider, Printing
from .fab_sets import gem_set_code
from ..treatments import encode_treatments


class FleshAndBloodProvider(GameProvider):
    game_id = "flesh-and-blood"
    display_name = "Flesh and Blood"

    def search(self, name: str) -> list[CardResult]:
        results = []
        for c in fabrary.search_cards(name):
            gem_sets = sorted({gem_set_code(p.get("print")) or "GEM"
                               for p in c.get("printings") or [] if p.get("set") == "GEM"})
            sets = []
            for set_name in c.get("sets") or []:
                sets.extend((gem_sets or ["GEM"]) if set_name == "GEM" else [set_name])
            results.append(
                CardResult(
                    identifier=c["cardIdentifier"],
                    name=c["name"],
                    image=card_image_url(c.get("defaultImage")),
                    sets=list(dict.fromkeys(sets)),
                    rarities=c.get("rarities") or [],
                )
            )
        return results

    def printings(self, card_identifier: str) -> list[Printing]:
        card = fabrary.get_card(card_identifier)
        if not card:
            return []
        out = []
        for p in card.get("printings") or []:
            tcg = p.get("tcgplayer") or {}
            out.append(
                Printing(
                    identifier=f"fab:{p['print']}",
                    set_code=gem_set_code(p["print"]) or p.get("set"),
                    edition=p.get("edition"),
                    foiling=p.get("foiling"),
                    treatment=encode_treatments(p.get("treatments") or []),
                    rarity=p.get("rarity"),
                    image=card_image_url(p.get("image")),
                    # Market prices are fetched separately from TCGplayer.
                    price=None,
                    currency=tcg.get("currency") or ("USD" if tcg.get("productId") else None),
                    price_source_id=str(tcg["productId"]) if tcg.get("productId") else None,
                    price_source_url=tcg.get("url"),
                )
            )
        return out

"""Flesh and Blood provider backed by FaBrary's AppSync API."""
from __future__ import annotations

from ..fabrary.client import card_image_url
from ..fabrary.client import client as fabrary
from .base import CardResult, GameProvider, Printing


class FleshAndBloodProvider(GameProvider):
    game_id = "flesh-and-blood"
    display_name = "Flesh and Blood"

    def search(self, name: str) -> list[CardResult]:
        results = []
        for c in fabrary.search_cards(name):
            results.append(
                CardResult(
                    identifier=c["cardIdentifier"],
                    name=c["name"],
                    image=card_image_url(c.get("defaultImage")),
                    sets=c.get("sets") or [],
                    rarities=c.get("rarities") or [],
                )
            )
        return results

    def printings(self, card_identifier: str) -> list[Printing]:
        card = fabrary.get_card(card_identifier)
        if not card:
            return []
        out = []
        for p in card.get("printingsWithPrices") or []:
            tcg = p.get("tcgplayer") or {}
            out.append(
                Printing(
                    identifier=p["identifier"],
                    set_code=p.get("set"),
                    edition=p.get("edition"),
                    foiling=p.get("foiling"),
                    treatment=p.get("treatment"),
                    rarity=p.get("rarity"),
                    image=card_image_url(p.get("image")),
                    # price stays a placeholder for now; we capture the
                    # tcgplayer product id/url so refresh can be wired later
                    price=None,
                    currency=tcg.get("currency"),
                    price_source_id=str(tcg["productId"]) if tcg.get("productId") else None,
                    price_source_url=tcg.get("url"),
                )
            )
        return out

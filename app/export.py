"""Buylist export: filtering + text rendering for Discord and .txt files.

Two output formats:
- Discord "WTB" message: grouped by set, one emoji per set header, each card
  line in the import format plus its suggested price (e.g. "3x RF Flowstate
  Embodiment 3$").
- Re-importable list: plain import-format lines (no grouping, no price) that
  paste straight back into the Import page.
"""
from __future__ import annotations

from .models import BuylistItem

# foiling value -> import code (standard/non-foil has no code)
_FOILING_CODE = {"Rainbow": "RF", "Cold": "CF", "Marvel": "MV"}
_DISCORD_HEADER = "WTB (OBO, price per card:"
_OTHERS = "Others"


def set_of(item: BuylistItem) -> str:
    return item.set_code or _OTHERS


def codes_for(item: BuylistItem) -> str:
    """Import-format codes for a printing, e.g. 'CF EA' (foiling then EA)."""
    parts = []
    fc = _FOILING_CODE.get(item.foiling or "")
    if fc:
        parts.append(fc)
    if (item.treatment or "").strip().lower() == "extended art":
        parts.append("EA")
    return " ".join(parts)


def display_printing(item: BuylistItem) -> str:
    """Short printing code for display/sorting: NF/CF/RF/MV, plus EA.
    (Standard/non-foil shows as NF, unlike the import codes where it's blank.)"""
    code = _FOILING_CODE.get(item.foiling or "", "NF")
    if (item.treatment or "").strip().lower() == "extended art":
        code += " EA"
    return code


def _price_str(value: float | None) -> str:
    if value is None:
        return ""
    if value == int(value):
        return f"{int(value)}$"
    return f"{value:g}$"


def card_line(item: BuylistItem, *, with_price: bool) -> str:
    codes = codes_for(item)
    mid = f"{codes} " if codes else ""
    line = f"{item.quantity}x {mid}{item.card_name}"
    if with_price:
        price = _price_str(item.suggested_price)
        if price:
            line += f" {price}"
    return line


def filter_items(
    items: list[BuylistItem],
    *,
    sets: set[str] | None = None,
    foilings: set | None = None,  # may contain None for standard
    price_min: float | None = None,
    price_max: float | None = None,
) -> list[BuylistItem]:
    range_set = price_min is not None or price_max is not None
    out = []
    for it in items:
        if sets is not None and set_of(it) not in sets:
            continue
        if foilings is not None and it.foiling not in foilings:
            continue
        if range_set:
            sp = it.suggested_price
            if sp is None:  # exclude unpriced when a price range is applied
                continue
            if price_min is not None and sp < price_min:
                continue
            if price_max is not None and sp > price_max:
                continue
        out.append(it)
    return out


def _grouped_by_set(items: list[BuylistItem]) -> list[tuple[str, list[BuylistItem]]]:
    groups: dict[str, list[BuylistItem]] = {}
    for it in items:
        groups.setdefault(set_of(it), []).append(it)
    # alphabetical, with "Others" last
    order = sorted(groups, key=lambda s: (s == _OTHERS, s.lower()))
    return [(s, groups[s]) for s in order]


def discord_text(items: list[BuylistItem]) -> str:
    lines = [_DISCORD_HEADER]
    for set_name, group in _grouped_by_set(items):
        lines.append("")
        lines.append(f"📦 {set_name}")
        for it in group:
            lines.append(card_line(it, with_price=True))
    return "\n".join(lines)


def reimport_text(items: list[BuylistItem]) -> str:
    return "\n".join(card_line(it, with_price=False) for it in items)

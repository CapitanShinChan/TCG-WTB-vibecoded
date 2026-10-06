"""Buylist export: filtering + text rendering for Discord and .txt files.

Two output formats:
- Discord "WTB" message: grouped by set, themed emojis per set header, each card
  line in the import format plus its suggested price (e.g. "3x RF Flowstate
  Embodiment 3$").
- Re-importable list: plain import-format lines (no grouping, no price) that
  paste straight back into the Import page.
"""
from __future__ import annotations

from .models import BuylistItem
from .providers.fab_sets import gem_set_code
from .treatments import has_treatment

# foiling value -> import code (standard/non-foil has no code)
_FOILING_CODE = {"Rainbow": "RF", "Cold": "CF", "Marvel": "MV"}
_DISCORD_HEADER = "WTB (OBO, price per card:"
_OTHERS = "Others"

# Wrapper colors from official pack artwork (source links in README.md).
_GEM_EMOJI = {
    "GEM1": "🔴",    # deep red
    "GEM2": "🔵",    # teal/blue
    "GEM3": "🔴🔵",  # red and blue/indigo
    "GEM4": "⚪",    # pearl/ivory
    "GEM5": "🔵🟣",  # cyan and purple
    "GEM6": "🟣",    # dark purple
}


def set_of(item: BuylistItem) -> str:
    # Older saved rows may still say GEM until startup normalization runs.
    # Resolve on read so choices, filters and both export formats agree now.
    if item.game == "flesh-and-blood":
        pack = gem_set_code(item.printing_id)
        if pack:
            return pack
    return item.set_code or _OTHERS


def codes_for(item: BuylistItem) -> str:
    """Import-format codes for a printing, e.g. 'CF EA' (foiling then EA)."""
    parts = []
    fc = _FOILING_CODE.get(item.foiling or "")
    if fc:
        parts.append(fc)
    if has_treatment(item.treatment, "Extended Art"):
        parts.append("EA")
    return " ".join(parts)


def display_printing(item: BuylistItem) -> str:
    """Short printing code for display/sorting: NF/CF/RF/MV, plus EA.
    (Standard/non-foil shows as NF, unlike the import codes where it's blank.)"""
    code = _FOILING_CODE.get(item.foiling or "", "NF")
    if has_treatment(item.treatment, "Extended Art"):
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
        # Export-only asking price: do not rewrite the saved suggestion.
        suggested = 0.5 if item.suggested_price == 0 else item.suggested_price
        price = _price_str(suggested)
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
    price_basis: str = "suggested",  # "suggested" or "current"
) -> list[BuylistItem]:
    range_set = price_min is not None or price_max is not None
    out = []
    for it in items:
        if sets is not None and set_of(it) not in sets:
            continue
        if foilings is not None and it.foiling not in foilings:
            continue
        if range_set:
            value = it.price if price_basis == "current" else it.suggested_price
            if value is None:  # exclude unpriced when a price range is applied
                continue
            if price_min is not None and value < price_min:
                continue
            if price_max is not None and value > price_max:
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
        emoji = (_GEM_EMOJI.get(set_name, "📦")
                 if all(it.game == "flesh-and-blood" for it in group) else "📦")
        lines.append(f"{emoji} {set_name}")
        for it in group:
            lines.append(card_line(it, with_price=True))
    return "\n".join(lines)


def reimport_text(items: list[BuylistItem]) -> str:
    return "\n".join(card_line(it, with_price=False) for it in items)

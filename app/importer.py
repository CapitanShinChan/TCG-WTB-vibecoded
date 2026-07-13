"""Parse a pasted card list and resolve each line to a real printing.

Line format (one card per line):

    3x Tempestuous Kiss
    1x RF Flowstate Embodiment
    1x CF EA Flowstate Embodiment

- Optional leading quantity: "3x" / "3" (defaults to 1).
- Optional printing-modifier codes between the quantity and the name:
    RF = Rainbow Foil, CF = Cold Foil, MV = Marvel  (foiling)
    NF = Non Foil / standard                         (foiling)
    EA = Extended Art                                (treatment)
- The rest of the line is the card name.

Resolution validates each card against a GameProvider (FaBrary for FaB): the
name must match exactly, and a printing matching the requested foiling/treatment
must exist. Card codes beginning with FAB / GEM / LGS are flagged as alt art.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .providers.base import GameProvider, Printing

# modifier code -> foiling value as FaBrary labels it (None == standard/non-foil)
_FOILING_CODES = {"RF": "Rainbow", "CF": "Cold", "MV": "Marvel", "NF": None}
_TREATMENT_CODES = {"EA"}
_ALL_CODES = set(_FOILING_CODES) | _TREATMENT_CODES
# card-code prefixes that indicate an alternate-art printing
_ALT_ART_PREFIXES = ("FAB", "GEM", "LGS")

_QTY_RE = re.compile(r"^(\d+)\s*[xX]?\s+(.*)$")


@dataclass
class ParsedLine:
    raw: str
    quantity: int
    name: str
    foiling: str | None  # None -> standard / non-foil
    extended_art: bool
    error: str | None = None


def parse_line(raw: str) -> ParsedLine | None:
    """Parse one line. Returns None for blank/comment lines."""
    line = raw.strip()
    if not line or line.startswith("#") or line.startswith("//"):
        return None

    m = _QTY_RE.match(line)
    if m:
        quantity = int(m.group(1))
        rest = m.group(2).strip()
    else:
        quantity = 1
        rest = line

    tokens = rest.split()
    foiling: str | None = None
    extended_art = False
    i = 0
    while i < len(tokens):
        code = tokens[i].upper()
        if code in _FOILING_CODES:
            foiling = _FOILING_CODES[code]
        elif code in _TREATMENT_CODES:
            extended_art = True
        else:
            break
        i += 1

    name = " ".join(tokens[i:]).strip()
    if not name:
        return ParsedLine(raw, quantity, "", foiling, extended_art, error="no card name")
    return ParsedLine(raw, quantity, name, foiling, extended_art)


def parse_list(text: str) -> list[ParsedLine]:
    out = []
    for raw in text.splitlines():
        parsed = parse_line(raw)
        if parsed is not None:
            out.append(parsed)
    return out


def _is_extended_art(p: Printing) -> bool:
    return (p.treatment or "").strip().lower() == "extended art"


def _is_alt_art(p: Printing) -> bool:
    ident = (p.identifier or "").upper()
    return any(ident.startswith(pfx) for pfx in _ALT_ART_PREFIXES)


def _is_short_print(p: Printing) -> bool:
    """Short-printed sets whose prices skew high; avoided when auto-picking a
    printing on import: History Pack, any First Edition, Welcome to Rathe Alpha.
    """
    set_name = (p.set_code or "").strip()
    edition = (p.edition or "").strip()
    if set_name.startswith("History Pack"):
        return True
    if edition == "First":
        return True
    if set_name == "Welcome to Rathe" and edition == "Alpha":
        return True
    return False


def _match_printing(
    printings: list[Printing], foiling: str | None, want_ea: bool
) -> Printing | None:
    candidates = [p for p in printings if (p.foiling or None) == foiling]
    if want_ea:
        candidates = [p for p in candidates if _is_extended_art(p)]
    else:
        non_ea = [p for p in candidates if not _is_extended_art(p)]
        candidates = non_ea or candidates  # accept EA-only if that's all there is
    if not candidates:
        return None
    # prefer normal (non short-print) sets, then a printing that has a
    # TCGplayer product id (so it can be priced). Short-print sets are only
    # used when nothing else matches the requested foiling.
    candidates.sort(
        key=lambda p: (_is_short_print(p), 0 if p.price_source_id else 1)
    )
    return candidates[0]


@dataclass
class ResolvedLine:
    raw: str
    quantity: int
    name: str
    requested_foiling: str | None
    requested_ea: bool
    status: str  # matched | no_printing | not_found | parse_error
    message: str | None = None
    card_identifier: str | None = None
    card_name: str | None = None
    printing: dict | None = None  # buylist-ready fields when matched

    def as_dict(self) -> dict:
        return {
            "raw": self.raw,
            "quantity": self.quantity,
            "name": self.name,
            "requested_foiling": self.requested_foiling,
            "requested_ea": self.requested_ea,
            "status": self.status,
            "message": self.message,
            "card_identifier": self.card_identifier,
            "card_name": self.card_name,
            "printing": self.printing,
        }


def _printing_payload(p: Printing) -> dict:
    return {
        "printing_id": p.identifier,
        "printing_label": p.label,
        "set_code": p.set_code,
        "foiling": p.foiling,
        "treatment": p.treatment,
        "rarity": p.rarity,
        "image_url": p.image,
        "currency": p.currency,
        "tcgplayer_product_id": p.price_source_id,
        "tcgplayer_url": p.price_source_url,
        "alt_art": _is_alt_art(p),
    }


def resolve_list(
    parsed_lines: list[ParsedLine], provider: GameProvider
) -> list[ResolvedLine]:
    """Resolve each parsed line against the provider. Caches per-name lookups."""
    # name (lower) -> (CardResult | None, list[Printing])
    cache: dict[str, tuple] = {}

    def lookup(name: str):
        key = name.lower()
        if key not in cache:
            results = provider.search(name)
            exact = next(
                (r for r in results if r.name.strip().lower() == key), None
            )
            printings = provider.printings(exact.identifier) if exact else []
            cache[key] = (exact, printings)
        return cache[key]

    resolved = []
    for pl in parsed_lines:
        if pl.error:
            resolved.append(
                ResolvedLine(
                    pl.raw, pl.quantity, pl.name, pl.foiling, pl.extended_art,
                    status="parse_error", message=pl.error,
                )
            )
            continue

        card, printings = lookup(pl.name)
        if not card:
            resolved.append(
                ResolvedLine(
                    pl.raw, pl.quantity, pl.name, pl.foiling, pl.extended_art,
                    status="not_found", message="No card with that exact name",
                )
            )
            continue

        match = _match_printing(printings, pl.foiling, pl.extended_art)
        if not match:
            want = _describe(pl.foiling, pl.extended_art)
            resolved.append(
                ResolvedLine(
                    pl.raw, pl.quantity, pl.name, pl.foiling, pl.extended_art,
                    status="no_printing", card_identifier=card.identifier,
                    card_name=card.name, message=f"No {want} printing found",
                )
            )
            continue

        resolved.append(
            ResolvedLine(
                pl.raw, pl.quantity, pl.name, pl.foiling, pl.extended_art,
                status="matched", card_identifier=card.identifier,
                card_name=card.name, printing=_printing_payload(match),
            )
        )
    return resolved


def _describe(foiling: str | None, ea: bool) -> str:
    bits = [foiling or "standard"]
    if ea:
        bits.append("Extended Art")
    return " ".join(bits)

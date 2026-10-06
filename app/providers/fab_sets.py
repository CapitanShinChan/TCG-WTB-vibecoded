"""FaB GEM pack labels; printed card IDs and variant identities stay unchanged.

Source-backed assignments are recorded in tests/fixtures/gem_pack_codes.json.
Bounds are explicit: packs have different sizes, and future codes must not be
silently assigned to GEM6.
"""
from __future__ import annotations

import re

_GEM_PRINTING = re.compile(r"(?:fab:)?GEM([0-9]{3})(?:-[^\r\n]+)?")
_GEM_PACKS = (
    (1, 32, "GEM1"),
    (33, 68, "GEM2"),
    (69, 104, "GEM3"),
    (105, 140, "GEM4"),
    (141, 183, "GEM5"),
    (184, 219, "GEM6"),
)
GEM_SET_CODES = tuple(code for _, _, code in _GEM_PACKS)


def gem_set_code(printing_id: str | None) -> str | None:
    """Recognize a complete legacy/canonical printing ID, without repairing it."""
    if not isinstance(printing_id, str):
        return None
    match = _GEM_PRINTING.fullmatch(printing_id)
    if match:
        number = int(match[1])
        for first, last, code in _GEM_PACKS:
            if first <= number <= last:
                return code
    return None


def normalize_gem_metadata(printing_id: str | None, set_code: str | None,
                           label: str | None) -> tuple[str | None, str | None]:
    """Correct only GEM set metadata; preserve IDs, art/foil details, and unknowns."""
    pack = gem_set_code(printing_id)
    if not pack:
        return set_code, label
    if isinstance(label, str):
        label = re.sub(r"^GEM(?:[1-6])?(?=\s|$)", pack, label, count=1)
    return pack, label

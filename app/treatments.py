"""Lossless treatment arrays with backwards-compatible scalar DB storage.

New values are JSON arrays in the existing text column/API field. Old single
labels remain readable, so no destructive database migration is necessary.
"""
from __future__ import annotations

import json


def treatment_names(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (ValueError, TypeError):
        return [value.strip()]
    if isinstance(parsed, list) and all(isinstance(x, str) for x in parsed):
        return parsed
    return [value.strip()]


def has_treatment(value: str | None, name: str) -> bool:
    return any(t.strip().casefold() == name.casefold() for t in treatment_names(value))


def encode_treatments(values: list[str]) -> str | None:
    return json.dumps(values, ensure_ascii=False) if values else None

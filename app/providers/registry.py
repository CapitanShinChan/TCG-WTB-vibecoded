"""Registry of available game providers.

To add a game later: implement a GameProvider and register it here. The UI game
selector is driven entirely by this dict.
"""
from __future__ import annotations

from .base import GameProvider
from .flesh_and_blood import FleshAndBloodProvider

_PROVIDERS: dict[str, GameProvider] = {
    p.game_id: p for p in (FleshAndBloodProvider(),)
}


def all_games() -> list[GameProvider]:
    return list(_PROVIDERS.values())


def get_provider(game_id: str) -> GameProvider | None:
    return _PROVIDERS.get(game_id)

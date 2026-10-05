"""Game-agnostic provider interface.

Each supported game implements a GameProvider that knows how to search that
game's card database and enumerate a card's printings. Pricing is fetched
separately when buylist prices are refreshed.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ..treatments import treatment_names


@dataclass
class CardResult:
    """A card as returned by a name search (one entry per unique card)."""

    identifier: str
    name: str
    image: str | None = None
    sets: list[str] = field(default_factory=list)
    rarities: list[str] = field(default_factory=list)


@dataclass
class Printing:
    """A single printing/variant of a card that can be added to the buylist."""

    identifier: str
    set_code: str | None = None
    edition: str | None = None
    foiling: str | None = None
    treatment: str | None = None  # JSON array of labels; legacy single labels accepted
    rarity: str | None = None
    image: str | None = None
    # pricing placeholder — populated later once price lookup is wired up
    price: float | None = None
    currency: str | None = None
    price_source_id: str | None = None  # e.g. tcgplayer productId
    price_source_url: str | None = None

    @property
    def label(self) -> str:
        """Human-readable printing description (set + treatment/foiling)."""
        bits = [b for b in (self.set_code, self.edition, *treatment_names(self.treatment), self.foiling) if b]
        return " ".join(bits) if bits else self.identifier


class GameProvider(ABC):
    game_id: str
    display_name: str

    @abstractmethod
    def search(self, name: str) -> list[CardResult]:
        ...

    @abstractmethod
    def printings(self, card_identifier: str) -> list[Printing]:
        ...

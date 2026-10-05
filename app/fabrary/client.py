"""FaBrary card metadata from a versioned, persistent JSON catalogue.

Search and card lookup are local after the first download. Prices are still
fetched separately by app.pricing.tcgplayer. No Cognito or GraphQL is used.
"""
from __future__ import annotations

import json
import logging
import math
import os
from pathlib import Path
import re
import tempfile
import threading
import time

import requests

from ..logging_setup import logged_request

CDN_BASE = "https://content.fabrary.net"
APP_INFO_URL = f"{CDN_BASE}/info/app-info.json"
_DEFAULT_CACHE = Path(__file__).resolve().parents[2] / ".cache" / "fabrary-catalogue.json"
_VERSION = re.compile(r"[0-9]+(?:\.[0-9]+){2}")


def card_image_url(image_key: str | None) -> str | None:
    if not image_key:
        return None
    if image_key.startswith(("https://", "http://")):
        return image_key
    return f"{CDN_BASE}/cards/{image_key}.webp"


class FabraryError(RuntimeError):
    """The catalogue is unavailable or its schema is not supported."""


class FabraryClient:
    def __init__(self, cache_path: Path | None = None, *, refresh_seconds=3600,
                 retry_seconds=60, clock=time.time) -> None:
        self.cache_path = Path(cache_path or os.getenv("APP_CATALOGUE_CACHE") or _DEFAULT_CACHE)
        self.refresh_seconds = refresh_seconds
        self.retry_seconds = retry_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._refresh_lock = threading.Lock()
        self._cards: dict[str, dict] = {}
        self._version: str | None = None
        self._checked_at = 0.0
        self._next_check = 0.0
        self._disk_loaded = False
        self._error: str | None = None
        self._save_error: str | None = None

    def _fetch_json(self, url: str) -> dict:
        response = logged_request("GET", url, service="fabrary", timeout=(10, 30))
        if response.status_code != 200:
            raise FabraryError(f"Catalogue HTTP {response.status_code}")
        return response.json()

    def _save(self, snapshot: dict) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        # Same-directory replacement is atomic; a partial download never
        # overwrites the previous catalogue. Unique staging names avoid clashes.
        name = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False,
                                             dir=self.cache_path.parent, suffix=".tmp") as f:
                name = f.name
                json.dump(snapshot, f, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(name, self.cache_path)
        finally:
            if name and os.path.exists(name):
                os.unlink(name)

    @staticmethod
    def _validate(version, cards) -> dict[str, dict]:
        if not isinstance(version, str) or not _VERSION.fullmatch(version):
            raise FabraryError("Invalid catalogue version")
        if not isinstance(cards, list) or not cards:
            raise FabraryError("Catalogue must contain a non-empty cards array")
        index = {}
        print_ids = set()
        for card in cards:
            if not isinstance(card, dict) or any(
                not isinstance(card.get(k), str) or not card[k]
                for k in ("cardIdentifier", "name")
            ):
                raise FabraryError("Catalogue card is missing its identifier or name")
            for field in ("sets", "rarities"):
                values = card.get(field)
                if values is not None and (not isinstance(values, list) or
                                           any(not isinstance(v, str) for v in values)):
                    raise FabraryError(f"Catalogue {field} must be a string array")
            if card.get("defaultImage") is not None and not isinstance(card["defaultImage"], str):
                raise FabraryError("Invalid catalogue card image")
            if card.get("pitch") is not None and type(card["pitch"]) is not int:
                raise FabraryError("Invalid catalogue pitch")
            if card.get("isCardBack") is not None and type(card["isCardBack"]) is not bool:
                raise FabraryError("Invalid catalogue card-back flag")
            ident = card["cardIdentifier"]
            if ident in index:
                raise FabraryError("Duplicate catalogue card identifier")
            printings = card.get("printings")
            if not isinstance(printings, list) or not printings:
                raise FabraryError("Catalogue card is missing its printings")
            for printing in printings:
                if not isinstance(printing, dict) or any(
                    not isinstance(printing.get(k), str) or not printing[k]
                    for k in ("identifier", "print")
                ):
                    raise FabraryError("Catalogue printing is missing its variant ID")
                if printing["print"] in print_ids:
                    raise FabraryError("Duplicate catalogue printing variant ID")
                print_ids.add(printing["print"])
                for field in ("image", "set", "edition", "foiling", "rarity"):
                    value = printing.get(field)
                    if value is not None and not isinstance(value, str):
                        raise FabraryError(f"Invalid catalogue printing {field}")
                treatments = printing.get("treatments")
                if treatments is not None and (not isinstance(treatments, list) or
                                               any(not isinstance(t, str) for t in treatments)):
                    raise FabraryError("Catalogue treatments must be a string array")
                tcg = printing.get("tcgplayer")
                if tcg is not None:
                    if not isinstance(tcg, dict):
                        raise FabraryError("Invalid catalogue TCGplayer reference")
                    product = tcg.get("productId")
                    if product is not None and type(product) not in (str, int):
                        raise FabraryError("Invalid catalogue TCGplayer product ID")
                    if any(tcg.get(k) is not None and not isinstance(tcg[k], str)
                           for k in ("url", "currency")):
                        raise FabraryError("Invalid catalogue TCGplayer URL/currency")
            index[ident] = card
        return index

    def _load_disk(self, now: float) -> None:
        self._disk_loaded = True
        try:
            snapshot = json.loads(self.cache_path.read_text(encoding="utf-8"))
            index = self._validate(snapshot["version"], snapshot["cards"])
            checked_at = float(snapshot["checked_at"])
            if not math.isfinite(checked_at) or checked_at < 0 or checked_at > now:
                checked_at = 0  # force revalidation after a clock change
            self._cards = index
            self._version = snapshot["version"]
            self._checked_at = checked_at
            self._next_check = checked_at + self.refresh_seconds
        except FileNotFoundError:
            pass
        except (OSError, ValueError, KeyError, TypeError, FabraryError) as exc:
            logging.getLogger(__name__).warning("Ignoring invalid catalogue cache: %s", exc)

    def _ensure_loaded(self) -> None:
        with self._lock:
            now = self._clock()
            if not self._disk_loaded:
                self._load_disk(now)
            if now < self._next_check:
                if self._cards:
                    return
                raise FabraryError(self._error or "Catalogue unavailable")
            warm = bool(self._cards)
        # Cold callers share one download. Warm callers never queue behind a
        # network refresh: they can continue using the previous snapshot.
        if not self._refresh_lock.acquire(blocking=not warm):
            return
        try:
            with self._lock:
                if self._clock() < self._next_check:
                    if self._cards:
                        return
                    raise FabraryError(self._error or "Catalogue unavailable")
            self._refresh()
        finally:
            self._refresh_lock.release()

    def _refresh(self) -> None:
        # Only the refresh owner calls this. Network and file I/O do not hold
        # the state lock; publish the validated snapshot in one short section.
        try:
            info = self._fetch_json(APP_INFO_URL)
            version = info.get("latestCardsVersion")
            if not isinstance(version, str) or not _VERSION.fullmatch(version):
                raise FabraryError("Invalid catalogue version in app-info.json")
            cards = list(self._cards.values()) if version == self._version else self._fetch_json(
                f"{CDN_BASE}/info/cards-{version}.json"
            )["cards"]
            index = self._validate(version, cards)
            checked_at = self._clock()
            snapshot = {"version": version, "checked_at": checked_at, "cards": cards}
            save_error = None
            try:
                self._save(snapshot)
            except OSError as exc:
                save_error = f"Catalogue loaded in memory but could not be saved: {exc}"
                logging.getLogger(__name__).warning(save_error)
            with self._lock:
                self._cards = index
                self._version = version
                self._checked_at = checked_at
                self._save_error = save_error
                self._next_check = checked_at + (self.retry_seconds if save_error else self.refresh_seconds)
                self._error = None
        except (requests.RequestException, OSError, ValueError, KeyError, TypeError,
                AttributeError, FabraryError) as exc:
            error = f"Catalogue refresh failed: {exc}"
            with self._lock:
                self._error = error
                self._next_check = self._clock() + self.retry_seconds
                unavailable = not self._cards
            logging.getLogger(__name__).warning(error)
            if unavailable:
                raise FabraryError(error) from exc

    def status(self) -> dict:
        """Inspect state without triggering a download."""
        with self._lock:
            return {"available": bool(self._cards), "version": self._version,
                    "checked_at": self._checked_at or None,
                    "stale": bool(self._cards) and (
                        bool(self._error) or self._clock() >= self._checked_at + self.refresh_seconds
                    ), "persistent": bool(self._cards) and not self._save_error,
                    "error": self._error or self._save_error,
                    "refreshing": self._refresh_lock.locked()}

    def search_cards(self, name: str) -> list[dict]:
        """Case-insensitive literal name substring search, exact matches first."""
        query = name.strip().casefold()
        if not query:
            return []
        self._ensure_loaded()
        matches = [c for c in self._cards.values()
                   if not c.get("isCardBack") and query in c["name"].casefold()]
        return sorted(matches, key=lambda c: (
            c["name"].casefold() != query, c["name"].casefold(),
            c.get("pitch") or 0, c["cardIdentifier"],
        ))

    def get_card(self, card_identifier: str) -> dict | None:
        self._ensure_loaded()
        return self._cards.get(card_identifier)


client = FabraryClient()

"""TCGplayer price lookup via the (unofficial) Infinite API.

The product page on tcgplayer.com fetches its price history from
infinite-api.tcgplayer.com. That endpoint is CORS-locked to the tcgplayer.com
origin but needs no auth, so we replay the same Origin/Referer headers.

Suggested price algorithm (per product):
  1. Pick the Near Mint / English SKU (fallback: first SKU).
  2. Build a list of sale prices: for each time bucket that had sales, take the
     midpoint of its low/high sale price, repeated `quantitySold` times
     (weighting by quantity to approximate individual sales).
  3. average = mean(prices). If there are >= 10 prices, discard the highest 25%
     and average the remainder. That trimmed mean is the suggested price.
The current price is the most recent bucket's market price.
"""
from __future__ import annotations

from dataclasses import dataclass

import requests

INFINITE_BASE = "https://infinite-api.tcgplayer.com"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) "
        "Gecko/20100101 Firefox/152.0"
    ),
    "Accept": "*/*",
    "Origin": "https://www.tcgplayer.com",
    "Referer": "https://www.tcgplayer.com/",
}
CURRENCY = "USD"  # TCGplayer prices are USD


class TCGPlayerError(RuntimeError):
    pass


@dataclass
class PricingResult:
    current_price: float | None  # latest market price listed on TCGplayer
    suggested_price: float | None  # trimmed mean of weighted sale prices
    sample_size: int  # number of sale-price points used
    currency: str = CURRENCY


@dataclass
class SalePoint:
    """One sale bucket (TCGplayer aggregates sales into short date buckets)."""

    date: str | None
    quantity: int
    low: float
    high: float
    price: float  # midpoint used in the suggested-price calc


def fetch_price_history(product_id: str | int, range_: str = "quarter") -> dict:
    url = f"{INFINITE_BASE}/price/history/{product_id}/detailed"
    headers = {
        **_HEADERS,
        "X-PageRequest-ID": f"card-inventory:www.tcgplayer.com/product/{product_id}",
    }
    resp = requests.get(
        url, params={"range": range_}, headers=headers, timeout=20
    )
    if resp.status_code != 200:
        raise TCGPlayerError(f"HTTP {resp.status_code}: {resp.text[:200]}")
    return resp.json()


def _select_sku(results: list[dict]) -> dict | None:
    for sku in results:
        if sku.get("condition") == "Near Mint" and sku.get("language") == "English":
            return sku
    return results[0] if results else None


def _to_float(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _weighted_sale_prices(sku: dict) -> list[float]:
    prices: list[float] = []
    for b in sku.get("buckets") or []:
        qty = int(_to_float(b.get("quantitySold")))
        if qty <= 0:
            continue
        low = _to_float(b.get("lowSalePrice"))
        high = _to_float(b.get("highSalePrice"))
        if low <= 0 and high <= 0:
            continue
        if low > 0 and high > 0:
            mid = (low + high) / 2
        else:
            mid = low or high  # only one side present
        prices.extend([mid] * qty)
    return prices


def _current_market_price(sku: dict) -> float | None:
    # buckets are newest-first; take the most recent non-zero market price
    for b in sku.get("buckets") or []:
        mp = _to_float(b.get("marketPrice"))
        if mp > 0:
            return mp
    return None


def _trimmed_mean(prices: list[float]) -> float | None:
    if not prices:
        return None
    if len(prices) >= 10:
        ordered = sorted(prices)
        drop = int(len(ordered) * 0.25)  # discard the highest 25%
        kept = ordered[: len(ordered) - drop] if drop else ordered
        return sum(kept) / len(kept)
    return sum(prices) / len(prices)


def compute_pricing(data: dict) -> PricingResult:
    sku = _select_sku(data.get("result") or [])
    if not sku:
        return PricingResult(None, None, 0)
    prices = _weighted_sale_prices(sku)
    suggested = _trimmed_mean(prices)
    return PricingResult(
        current_price=_current_market_price(sku),
        suggested_price=round(suggested, 2) if suggested is not None else None,
        sample_size=len(prices),
    )


def get_pricing(product_id: str | int, range_: str = "quarter") -> PricingResult:
    return compute_pricing(fetch_price_history(product_id, range_))


def extract_sales(data: dict) -> list[SalePoint]:
    """Sale buckets for the selected SKU, newest first (same SKU the suggested
    price is computed from)."""
    sku = _select_sku(data.get("result") or [])
    sales: list[SalePoint] = []
    if not sku:
        return sales
    for b in sku.get("buckets") or []:  # buckets are newest-first
        qty = int(_to_float(b.get("quantitySold")))
        if qty <= 0:
            continue
        low = _to_float(b.get("lowSalePrice"))
        high = _to_float(b.get("highSalePrice"))
        if low <= 0 and high <= 0:
            continue
        mid = (low + high) / 2 if (low > 0 and high > 0) else (low or high)
        sales.append(
            SalePoint(
                date=b.get("bucketStartDate"),
                quantity=qty,
                low=round(low, 2),
                high=round(high, 2),
                price=round(mid, 2),
            )
        )
    return sales


def get_sales(product_id: str | int, range_: str = "quarter") -> list[SalePoint]:
    return extract_sales(fetch_price_history(product_id, range_))

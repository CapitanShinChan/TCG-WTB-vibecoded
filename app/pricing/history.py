"""Bounded current-market observations, oldest first (not upstream sale buckets)."""
from __future__ import annotations

from datetime import datetime, timezone
import math

HISTORY_LIMIT = 10


def valid_price(price) -> bool:
    return type(price) in (int, float) and math.isfinite(price) and price >= 0


def saved_history(item) -> list[dict]:
    """Include the last pre-history snapshot without inventing an observation date."""
    if item.price_history:
        return list(item.price_history)
    if not valid_price(item.price):
        return []
    at = item.price_updated_at
    if at is not None:
        at = at.replace(tzinfo=timezone.utc) if at.tzinfo is None else at.astimezone(timezone.utc)
    return [{"price": item.price, "at": at.isoformat() if at else None, "currency": item.currency}]


def record_price(item, price: float | None, at, currency: str) -> None:
    history = saved_history(item)
    if price is not None:
        # Never draw a trend across incompatible units.
        history = [p for p in history if p["currency"] == currency]
        history.append({"price": price, "at": at.isoformat(), "currency": currency})
    # Assign a fresh list so SQLAlchemy detects and persists JSON changes.
    item.price_history = history[-HISTORY_LIMIT:]


def merge_pricing(target, source) -> None:
    """Keep one whole pricing snapshot and the newest ten comparable observations."""
    observations = saved_history(target) + saved_history(source)
    source_priced = source.price is not None or source.suggested_price is not None
    target_priced = target.price is not None or target.suggested_price is not None
    source_at = source.price_updated_at
    target_at = target.price_updated_at
    # SQLite returns naive datetimes for UTC timestamps; compare them
    # with aware values without depending on the host's local timezone.
    if source_at is not None:
        source_at = (source_at.replace(tzinfo=timezone.utc)
                     if source_at.tzinfo is None else source_at.astimezone(timezone.utc))
    if target_at is not None:
        target_at = (target_at.replace(tzinfo=timezone.utc)
                     if target_at.tzinfo is None else target_at.astimezone(timezone.utc))
    if source_priced and (not target_priced or (
        source_at is not None and (target_at is None or source_at > target_at)
    )):
        for field in ("price", "suggested_price", "price_sample_size", "price_updated_at", "currency"):
            setattr(target, field, getattr(source, field))
    unique = {}
    for point in observations:
        if point["currency"] != target.currency:
            continue
        # Same dated observation copied between lists counts once; target wins ties.
        key = (point["at"], point["currency"], point["price"] if point["at"] is None else None)
        unique.setdefault(key, point)
    target.price_history = sorted(unique.values(), key=lambda p: p["at"] or "")[-HISTORY_LIMIT:]


def sparkline(history) -> dict:
    """Geometry and accessible text for a tiny, individually scaled SVG chart."""
    observations = [p for p in (history or []) if valid_price(p.get("price"))][-HISTORY_LIMIT:]
    if not observations:
        return {"points": [], "label": "Data points: 0\nChange: N/A\nLast update: Unknown"}
    prices = [p["price"] for p in observations]
    low, high = min(prices), max(prices)
    count = len(prices)
    points = []
    for i, p in enumerate(observations):
        x = 44 if count == 1 else 4 + 80 * i / (count - 1)
        y = 14 if high == low else 24 - 20 * (p["price"] - low) / (high - low)
        points.append({"x": f"{x:.2f}", "y": f"{y:.2f}"})
    direction = "up" if prices[-1] > prices[0] else "down" if prices[-1] < prices[0] else "flat"
    # Keep the reference consistent with the graph's first-to-last direction.
    # High/low are extrema of the displayed observations, not local turning points.
    change = "N/A"
    if count > 1:
        if direction == "flat":
            change = "0.00%"
        else:
            reference = "low" if direction == "up" else "high"
            baseline = low if direction == "up" else high
            if baseline == 0:
                change = f"N/A ({reference} is zero)"
            else:
                percent = (prices[-1] - baseline) / baseline * 100
                if math.isfinite(percent):
                    change = f"{percent:+.2f}% from {reference}"
    updated = "Unknown"
    try:
        timestamp = datetime.fromisoformat(observations[-1].get("at"))
        timestamp = (timestamp.replace(tzinfo=timezone.utc) if timestamp.tzinfo is None
                     else timestamp.astimezone(timezone.utc))
        updated = f"{timestamp.year:04d}/{timestamp.month:02d}/{timestamp.day:02d}"
    except (TypeError, ValueError, OverflowError):
        pass  # Do not invent a date for legacy observations without timestamps.
    label = f"Data points: {count}\nChange: {change}\nLast update: {updated}"
    return {"points": points, "line": " ".join(f"{p['x']},{p['y']}" for p in points),
            "direction": direction, "label": label}

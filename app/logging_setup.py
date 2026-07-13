"""HTTP logging: a compact human-readable access log plus a JSON-Lines (ECS)
detailed log, and helpers for logging incoming and outgoing requests.

- logs/access.log  — one compact line per request (eyeballing/debugging)
- logs/http.jsonl  — one ECS JSON object per line (log-aggregator ingestion)

Both cover incoming ("local") requests to this app and outgoing requests to
external services (FaBrary, TCGplayer, Cognito).
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import time
from logging.handlers import RotatingFileHandler

import requests

from .config import LOG_DIR

_ACCESS = logging.getLogger("cardinv.access")
_DETAIL = logging.getLogger("cardinv.detail")
_configured = False


def setup_logging() -> None:
    global _configured
    if _configured:
        return
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    plain = logging.Formatter("%(message)s")  # lines are pre-formatted here

    access_h = RotatingFileHandler(
        LOG_DIR / "access.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    access_h.setFormatter(plain)
    _ACCESS.handlers = [access_h]
    _ACCESS.setLevel(logging.INFO)
    _ACCESS.propagate = False

    detail_h = RotatingFileHandler(
        LOG_DIR / "http.jsonl", maxBytes=5_000_000, backupCount=5, encoding="utf-8"
    )
    detail_h.setFormatter(plain)
    _DETAIL.handlers = [detail_h]
    _DETAIL.setLevel(logging.INFO)
    _DETAIL.propagate = False
    _configured = True


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def log_http(
    *,
    direction: str,  # "local" (incoming) or "outgoing"
    method: str,
    url: str,
    path: str | None = None,
    params: dict | None = None,
    status: int | None = None,
    duration_ms: float | None = None,
    service: str | None = None,
    error: object | None = None,
) -> None:
    """Write one HTTP event to both the access log and the ECS JSON log."""
    ts = _now_iso()

    # --- compact access line ---
    tag = "LOCAL" if direction == "local" else f"OUTGOING:{service or '?'}"
    uri = path or url
    param_str = ""
    if params:
        param_str = " " + " ".join(f"{k}={v}" for k, v in params.items())
    dur = f"{duration_ms:.0f}ms" if duration_ms is not None else "-"
    st = status if status is not None else ("ERR" if error else "-")
    _ACCESS.info(f"{ts} | {tag} | {method} {uri} | {st} | {dur}{param_str}")

    # --- ECS JSON-Lines detail ---
    doc = {
        "@timestamp": ts,
        "event": {
            "kind": "event",
            "category": ["web"],
            # ECS event.duration is in nanoseconds
            "duration": int(duration_ms * 1_000_000)
            if duration_ms is not None
            else None,
            "outcome": "failure" if error else "success",
        },
        "network": {"direction": "inbound" if direction == "local" else "outbound"},
        "service": {"name": service or "card-inventory"},
        "http": {
            "request": {"method": method},
            "response": {"status_code": status},
        },
        "url": {"full": url, "path": path},
        "params": params or {},
    }
    if error is not None:
        doc["error"] = {"message": str(error), "type": type(error).__name__}
    _DETAIL.info(json.dumps(doc, default=str))


def logged_request(
    method: str,
    url: str,
    *,
    service: str,
    params_log: dict | None = None,
    **kwargs,
) -> requests.Response:
    """`requests` wrapper that logs the outgoing call (to both logs)."""
    start = time.perf_counter()
    status = None
    error = None
    try:
        resp = requests.request(method, url, **kwargs)
        status = resp.status_code
        return resp
    except Exception as e:  # noqa: BLE001 - re-raised after logging
        error = e
        raise
    finally:
        log_http(
            direction="outgoing",
            method=method.upper(),
            url=url,
            path=url,
            params=params_log,
            status=status,
            duration_ms=(time.perf_counter() - start) * 1000,
            service=service,
            error=error,
        )

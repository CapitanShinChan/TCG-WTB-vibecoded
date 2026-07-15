"""Single-user HTTP Basic auth with brute-force throttling.

Credentials are never hardcoded in tracked source. They are loaded with this
precedence:

  1. Environment variables (production):
       AUTH_USERNAME, AUTH_SALT (hex), AUTH_PASSWORD_HASH (hex)
  2. A local, git-ignored file `auth_local.json` at the project root
     (for local testing) — see auth_local.example.json.
  3. Nothing configured -> auth fails closed (every request is rejected).

The password is a salted PBKDF2-SHA256 hash. To generate salt/hash:

    python -c "import hashlib,secrets; s=secrets.token_hex(16); \
      print(s, hashlib.pbkdf2_hmac('sha256', b'NEWPASS', bytes.fromhex(s), 200_000).hex())"

Basic auth sends credentials every request, so serve only over HTTPS.

Brute-force protection (in-memory, per source IP; single instance):
  - a fixed delay is applied to every *failed* attempt;
  - after a few failures an IP is locked out with exponential backoff (429);
  - a success, or a period of inactivity, resets an IP's counter.
Only requests that actually present (wrong) credentials are penalised — a
browser's initial credential-less request just gets the auth challenge.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import threading
import time
from pathlib import Path

_ITERATIONS = 200_000
_LOCAL_FILE = Path(__file__).resolve().parent.parent / "auth_local.json"


def _load_credentials() -> tuple[str | None, str | None, str | None]:
    """(username, salt, password_hash). Missing pieces -> (None, None, None)."""
    if os.getenv("AUTH_PASSWORD_HASH"):
        return (
            os.getenv("AUTH_USERNAME", "shinchan"),
            os.getenv("AUTH_SALT", ""),
            os.getenv("AUTH_PASSWORD_HASH"),
        )
    if _LOCAL_FILE.exists():
        try:
            data = json.loads(_LOCAL_FILE.read_text(encoding="utf-8"))
            return data["username"], data["salt"], data["password_hash"]
        except (ValueError, KeyError, OSError):
            pass
    return (None, None, None)


_USERNAME, _SALT, _PASSWORD_HASH = _load_credentials()


def _hash(password: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(_SALT or ""), _ITERATIONS
    ).hex()


def check_credentials(username: str, password: str) -> bool:
    if not _PASSWORD_HASH or not _USERNAME:
        return False  # fail closed when no credentials are configured
    user_ok = hmac.compare_digest(username, _USERNAME)
    pass_ok = hmac.compare_digest(_hash(password), _PASSWORD_HASH)
    return user_ok and pass_ok


def is_authorized(authorization_header: str | None) -> bool:
    """Validate an HTTP `Authorization: Basic <base64>` header."""
    if not authorization_header:
        return False
    scheme, _, token = authorization_header.partition(" ")
    if scheme.lower() != "basic" or not token:
        return False
    try:
        decoded = base64.b64decode(token).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return False
    username, _, password = decoded.partition(":")
    return check_credentials(username, password)


# --- brute-force throttling ------------------------------------------------

FAILURE_DELAY = 0.5   # seconds, applied to every failed attempt
_FREE_ATTEMPTS = 5    # failures allowed before lockout starts
_BASE_LOCK = 1.0      # base lockout (seconds)
_MAX_LOCK = 300.0     # lockout cap (seconds)
_RESET_AFTER = 900.0  # forget an IP's failures after this idle time (seconds)

_lock = threading.Lock()
_state: dict[str, dict] = {}  # ip -> {failures, blocked_until, last}


def seconds_blocked(ip: str) -> float:
    """Remaining lockout for an IP (0 if not blocked)."""
    now = time.monotonic()
    with _lock:
        s = _state.get(ip)
        if not s:
            return 0.0
        if now - s["last"] > _RESET_AFTER:
            _state.pop(ip, None)
            return 0.0
        return max(0.0, s["blocked_until"] - now)


def record_failure(ip: str) -> None:
    now = time.monotonic()
    with _lock:
        s = _state.setdefault(ip, {"failures": 0, "blocked_until": 0.0, "last": now})
        s["failures"] += 1
        s["last"] = now
        if s["failures"] > _FREE_ATTEMPTS:
            backoff = _BASE_LOCK * (2 ** (s["failures"] - _FREE_ATTEMPTS - 1))
            s["blocked_until"] = now + min(backoff, _MAX_LOCK)


def record_success(ip: str) -> None:
    with _lock:
        _state.pop(ip, None)

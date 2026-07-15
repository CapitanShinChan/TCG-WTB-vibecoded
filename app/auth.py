"""Simple single-user HTTP Basic auth.

Credentials are stored here as a salted PBKDF2-SHA256 hash (not plaintext), so
the password never sits in the repo/git history. The username and hash can be
overridden in production via environment variables:

    AUTH_USERNAME
    AUTH_SALT           (hex)
    AUTH_PASSWORD_HASH  (hex, pbkdf2_hmac sha256, 200k iterations of the salt)

To change the password, regenerate SALT/HASH:

    python -c "import hashlib,secrets; s=secrets.token_hex(16); \
      print(s, hashlib.pbkdf2_hmac('sha256', b'NEWPASS', bytes.fromhex(s), 200_000).hex())"

Basic auth sends credentials on every request, so only serve this over HTTPS
(Azure App Service provides TLS).
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os

_ITERATIONS = 200_000

USERNAME = os.getenv("AUTH_USERNAME", "shinchan")
_SALT = os.getenv("AUTH_SALT", "REDACTED_SALT_ROTATED")
_PASSWORD_HASH = os.getenv(
    "AUTH_PASSWORD_HASH",
    "REDACTED_HASH_ROTATED",
)


def _hash(password: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(_SALT), _ITERATIONS
    ).hex()


def check_credentials(username: str, password: str) -> bool:
    # constant-time comparisons to avoid timing leaks
    user_ok = hmac.compare_digest(username, USERNAME)
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

"""FaBrary AppSync GraphQL client.

FaBrary's card database is served from an AWS AppSync GraphQL API guarded by
AWS_IAM auth. Anonymous access is granted through a Cognito Identity Pool
(unauthenticated identities), so we can mint short-lived AWS credentials without
any login, then SigV4-sign each GraphQL request. The API also sits behind AWS
WAF, which rejects requests that don't look like they came from the FaBrary web
app, so we replay the same browser-ish headers the site uses.
"""
from __future__ import annotations

import datetime as dt
import json
import threading
from dataclasses import dataclass

import boto3
import botocore
import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials

REGION = "us-east-2"
IDENTITY_POOL_ID = "us-east-2:e50f3ed7-32ed-4b22-a05e-10b3e7e03fe0"
APPSYNC_URL = (
    "https://42xrd23ihbd47fjvsrt27ufpfe.appsync-api.us-east-2.amazonaws.com/graphql"
)
# FaBrary serves card art from this CDN. The GraphQL API returns only an image
# key (e.g. "GEM096"); the full URL is <CDN>/cards/<key>.webp
CDN_BASE = "https://content.fabrary.net"


def card_image_url(image_key: str | None) -> str | None:
    if not image_key:
        return None
    # already a full URL? pass through
    if image_key.startswith("http"):
        return image_key
    return f"{CDN_BASE}/cards/{image_key}.webp"

# Headers the AWS WAF in front of AppSync expects. x-amz-user-agent is part of
# the SigV4 signed headers; the rest are unsigned but still inspected by WAF.
_SIGNED_EXTRA = {"x-amz-user-agent": "aws-amplify/5.3.11 api/1 framework/1"}
_UNSIGNED_EXTRA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) "
        "Gecko/20100101 Firefox/152.0"
    ),
    "Origin": "https://fabrary.net",
    "Referer": "https://fabrary.net/",
    "Accept": "application/json, text/plain, */*",
}

# --- GraphQL documents -----------------------------------------------------

_SEARCH_CARDS = """query searchCards($text: String!) {
  searchCards(text: $text) {
    cardIdentifier
    name
    defaultImage
    rarities
    sets
  }
}"""

_GET_CARD = """query getCard($cardIdentifier: ID!) {
  getCard(cardIdentifier: $cardIdentifier) {
    cardIdentifier
    name
    printingsWithPrices {
      identifier
      set
      edition
      foiling
      treatment
      rarity
      image
      tcgplayer { currency name price productId url }
    }
  }
}"""


class FabraryError(RuntimeError):
    """Raised when the AppSync API returns GraphQL errors or an HTTP failure."""


@dataclass
class _CachedCreds:
    creds: Credentials
    expires_at: dt.datetime


class FabraryClient:
    """Thread-safe client that caches Cognito creds and calls AppSync."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache: _CachedCreds | None = None
        self._cognito = boto3.client(
            "cognito-identity",
            region_name=REGION,
            config=botocore.config.Config(signature_version=botocore.UNSIGNED),
        )

    # -- credentials --------------------------------------------------------

    def _get_credentials(self) -> Credentials:
        now = dt.datetime.now(dt.timezone.utc)
        with self._lock:
            cache = self._cache
            # refresh a minute early to avoid using creds that expire mid-flight
            if cache and cache.expires_at - dt.timedelta(seconds=60) > now:
                return cache.creds

            identity_id = self._cognito.get_id(IdentityPoolId=IDENTITY_POOL_ID)[
                "IdentityId"
            ]
            raw = self._cognito.get_credentials_for_identity(IdentityId=identity_id)[
                "Credentials"
            ]
            creds = Credentials(
                raw["AccessKeyId"], raw["SecretKey"], raw["SessionToken"]
            )
            self._cache = _CachedCreds(creds=creds, expires_at=raw["Expiration"])
            return creds

    # -- low-level graphql --------------------------------------------------

    def _graphql(self, query: str, variables: dict) -> dict:
        creds = self._get_credentials()
        body = json.dumps({"query": query, "variables": variables})
        headers = {"Content-Type": "application/json; charset=UTF-8", **_SIGNED_EXTRA}
        req = AWSRequest(method="POST", url=APPSYNC_URL, data=body, headers=headers)
        SigV4Auth(creds, "appsync", REGION).add_auth(req)
        send_headers = {**dict(req.headers), **_UNSIGNED_EXTRA}
        resp = requests.post(APPSYNC_URL, data=body, headers=send_headers, timeout=20)
        if resp.status_code != 200:
            raise FabraryError(f"AppSync HTTP {resp.status_code}: {resp.text[:300]}")
        payload = resp.json()
        if payload.get("errors"):
            raise FabraryError(f"GraphQL errors: {json.dumps(payload['errors'])[:300]}")
        return payload["data"]

    # -- public API ---------------------------------------------------------

    def search_cards(self, name: str) -> list[dict]:
        """Search cards by name. Returns MinimalCard dicts."""
        text = f"name:{name.strip()}"
        data = self._graphql(_SEARCH_CARDS, {"text": text})
        return data.get("searchCards") or []

    def get_card(self, card_identifier: str) -> dict | None:
        """Full card with every printing (image + tcgplayer price ref)."""
        data = self._graphql(_GET_CARD, {"cardIdentifier": card_identifier})
        return data.get("getCard")


# module-level singleton; creds are cached and reused across requests
client = FabraryClient()

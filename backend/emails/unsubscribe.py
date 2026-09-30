"""Signed unsubscribe links for the weekly engagement email.

Shared by the enqueuer (scheduler — build the footer link) and the
/api/email/unsubscribe route (verify the link). The signature is an
HMAC-SHA256 over the lowercased address, keyed on the same secret used for
JWT tokens (config.JWT_SECRET / the dev fallback)."""

import base64
import hashlib
import hmac
import urllib.parse

from utils.jwt import ensure_secret

_BASE = "https://jobawn.com/api/email/unsubscribe"


def _sign(email: str) -> str:
    sig = hmac.new(ensure_secret().encode("utf-8"),
                   email.lower().encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig).rstrip(b"=").decode("ascii")


def build_unsubscribe_url(email: str) -> str:
    """Signed opt-out link for the engagement-email footer. Returns '' (no link)
    when the JWT secret is unavailable, so the enqueuer degrades gracefully."""
    try:
        raw = (email or "").strip().lower()
        if not raw:
            return ""
        return f"{_BASE}?email={urllib.parse.quote(raw)}&s={_sign(raw)}"
    except Exception:
        return ""


def validate_unsubscribe(email: str, sig: str) -> bool:
    """Confirm the signature matches the address (constant-time compare)."""
    try:
        raw = (email or "").strip().lower()
        if not raw or not sig:
            return False
        return hmac.compare_digest(_sign(raw), sig.strip())
    except Exception:
        return False
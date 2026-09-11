import base64
import hashlib
import hmac
import json
import time

from config import JWT_ACCESS_TOKEN_MINUTES, JWT_ALLOW_DEV_SECRET, JWT_SECRET

_DEV_SECRET = "jobawn-dev-secret-2f9c1a7e4b6d8f0a3c5e7b9d1f3a5c7e"

__all__ = ["JwtError", "create_token", "decode_token", "ensure_secret"]


class JwtError(Exception):
    pass


def _secret():
    if JWT_SECRET:
        return JWT_SECRET
    if JWT_ALLOW_DEV_SECRET:
        return _DEV_SECRET
    raise JwtError("JWT_SECRET is not set")


def ensure_secret() -> str:
    return _secret()


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def create_token(email: str, expires_minutes: int | None = None) -> str:
    minutes = expires_minutes if expires_minutes is not None else JWT_ACCESS_TOKEN_MINUTES
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload = {"sub": email, "iat": now, "exp": now + int(minutes) * 60}
    signing_input = (
        _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
        + "."
        + _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    )
    signature = _b64url(
        hmac.new(_secret().encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
    )
    return signing_input + "." + signature


def decode_token(token: str) -> dict:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            raise JwtError("malformed token")
        header_b64, payload_b64, signature = parts
        signing_input = header_b64 + "." + payload_b64
        expected = base64.urlsafe_b64encode(
            hmac.new(_secret().encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
        ).rstrip(b"=").decode("ascii")
        if not hmac.compare_digest(expected, signature):
            raise JwtError("bad signature")
        payload = json.loads(_b64url_decode(payload_b64))
        if payload.get("exp") and payload["exp"] < int(time.time()):
            raise JwtError("token expired")
        return payload
    except JwtError:
        raise
    except Exception as e:  # noqa: BLE001 - surface every malformed-token case as JwtError
        raise JwtError(str(e)) from e
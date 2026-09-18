from fastapi import Header, HTTPException

from utils.jwt import JwtError, decode_token

__all__ = ["get_current_user", "get_optional_user"]


def _decode(authorization: str) -> dict:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="Invalid or missing credentials")
    try:
        payload = decode_token(token.strip())
    except JwtError as e:
        raise HTTPException(status_code=401, detail="Invalid or missing credentials") from e
    email = (payload.get("sub") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=401, detail="Invalid or missing credentials")
    return {"email": email}


def _user_exists(email: str) -> bool:
    from db import get_user
    try:
        return get_user(email) is not None
    except Exception:
        return True


def get_current_user(authorization: str | None = Header(None)) -> dict:
    identity = _decode(authorization)
    if not _user_exists(identity["email"]):
        raise HTTPException(status_code=401, detail="Invalid or missing credentials")
    return identity


def get_optional_user(authorization: str | None = Header(None)) -> dict | None:
    if not authorization:
        return None
    try:
        identity = _decode(authorization)
    except HTTPException:
        return None
    if not _user_exists(identity["email"]):
        return None
    return identity
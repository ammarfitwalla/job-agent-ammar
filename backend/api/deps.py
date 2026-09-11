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
    email = (payload.get("sub") or "").strip()
    if not email:
        raise HTTPException(status_code=401, detail="Invalid or missing credentials")
    return {"email": email}


def get_current_user(authorization: str | None = Header(None)) -> dict:
    return _decode(authorization)


def get_optional_user(authorization: str | None = Header(None)) -> dict | None:
    if not authorization:
        return None
    try:
        return _decode(authorization)
    except HTTPException:
        return None
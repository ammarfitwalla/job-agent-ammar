from fastapi import APIRouter, Query, Request, HTTPException
from pydantic import BaseModel
from config import ROLES_BY_CATEGORY
from utils.client_ip import get_client_ip
from utils.rate_limiter import check_rate_limit
import db

router = APIRouter(prefix="/roles", tags=["roles"])

# Public custom role writes — cap per IP.
_CUSTOM_ROLE_RATE = 10
_CUSTOM_ROLE_WINDOW = 60


class RoleName(BaseModel):
    name: str


def _merged_roles():
    cats = dict(ROLES_BY_CATEGORY)
    custom = db.get_custom_roles()
    if custom:
        known = {r.lower() for roles in cats.values() for r in roles}
        unique = [r for r in custom if r.lower() not in known]
        if unique:
            cats["Custom"] = unique
    return cats


@router.get("")
async def get_roles():
    return {"categories": _merged_roles()}


@router.post("/custom")
async def add_custom_role(body: RoleName, request: Request = None):
    client_ip = get_client_ip(request)
    if client_ip and not check_rate_limit(f"custom_role:{client_ip}", _CUSTOM_ROLE_RATE, _CUSTOM_ROLE_WINDOW):
        raise HTTPException(429, "Too many requests. Try again later.")
    role_name = body.name.strip()
    if not role_name:
        return {"ok": False, "error": "missing name"}
    db.add_custom_role(role_name)
    return {"ok": True, "categories": _merged_roles()}


@router.delete("/custom")
async def delete_custom_role(name: str = Query(...), request: Request = None):
    client_ip = get_client_ip(request)
    if client_ip and not check_rate_limit(f"custom_role:{client_ip}", _CUSTOM_ROLE_RATE, _CUSTOM_ROLE_WINDOW):
        raise HTTPException(429, "Too many requests. Try again later.")
    db.delete_custom_role(name)
    return {"ok": True, "categories": _merged_roles()}

from fastapi import APIRouter, Query
from pydantic import BaseModel
from config import ROLES_BY_CATEGORY
import db

router = APIRouter(prefix="/roles", tags=["roles"])


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
async def add_custom_role(body: RoleName):
    role_name = body.name.strip()
    if not role_name:
        return {"ok": False, "error": "missing name"}
    db.add_custom_role(role_name)
    return {"ok": True, "categories": _merged_roles()}


@router.delete("/custom")
async def delete_custom_role(name: str = Query(...)):
    db.delete_custom_role(name)
    return {"ok": True, "categories": _merged_roles()}

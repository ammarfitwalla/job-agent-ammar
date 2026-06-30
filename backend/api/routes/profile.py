from fastapi import APIRouter, Query
from pydantic import BaseModel

from db import get_user, update_user_name, get_saved_jobs_status_counts

router = APIRouter(prefix="/api/profile", tags=["profile"])


class UpdateNameRequest(BaseModel):
    email: str
    name: str


@router.get("")
async def profile_get(email: str = Query("")):
    if not email:
        return {"error": "email required"}
    user = get_user(email)
    if not user:
        return {"error": "User not found"}
    status_counts = get_saved_jobs_status_counts(email)
    return {
        "email": user["email"],
        "name": user["name"],
        "created_at": user["created_at"],
        "status_counts": status_counts,
    }


@router.put("/name")
async def profile_update_name(req: UpdateNameRequest):
    update_user_name(req.email, req.name)
    return {"ok": True, "email": req.email, "name": req.name}

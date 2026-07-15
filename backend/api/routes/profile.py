from fastapi import APIRouter, Query
from pydantic import BaseModel

from db import get_user, update_user_name, update_user_profile, get_saved_jobs_status_counts

router = APIRouter(prefix="/api/profile", tags=["profile"])


class UpdateNameRequest(BaseModel):
    email: str
    name: str


class UpdateProfileRequest(BaseModel):
    email: str
    name: str | None = None
    company: str | None = None
    position: str | None = None
    linkedin_url: str | None = None


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
        "company": user.get("company", ""),
        "position": user.get("position", ""),
        "linkedin_url": user.get("linkedin_url", ""),
        "referral_credits": user.get("referral_credits", 0),
        "created_at": user["created_at"],
        "status_counts": status_counts,
    }


@router.put("/name")
async def profile_update_name(req: UpdateNameRequest):
    update_user_name(req.email, req.name)
    return {"ok": True, "email": req.email, "name": req.name}


@router.put("")
async def profile_update(req: UpdateProfileRequest):
    update_user_profile(
        req.email,
        name=req.name,
        company=req.company,
        position=req.position,
        linkedin_url=req.linkedin_url,
    )
    user = get_user(req.email)
    return {"ok": True, "user": user}

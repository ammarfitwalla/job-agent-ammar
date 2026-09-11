from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.deps import get_current_user
from config import ADMIN_EMAIL
from db import add_saved_job, is_job_saved, get_saved_jobs, get_saved_job_owner, update_saved_job_status, delete_saved_job, batch_check_saved, get_latest_referral_scores

router = APIRouter(prefix="/api/saved-jobs", tags=["saved-jobs"])


class SaveJobRequest(BaseModel):
    title: str = ""
    company: str = ""
    url: str = ""
    location: str = ""
    salary: str = ""
    total_score: int = 0
    ai_score: int = 0
    keyword_score: int = 0
    reason: str = ""
    experience_level: str = ""
    tags: list[str] = []
    site: str = ""


class UpdateStatusRequest(BaseModel):
    status: str


class BatchCheckRequest(BaseModel):
    urls: list[str] = []


@router.post("")
async def saved_jobs_create(req: SaveJobRequest, user: dict = Depends(get_current_user)):
    email = user["email"]
    result = add_saved_job(email, req.model_dump())
    return result


@router.get("")
async def saved_jobs_list(email: str = Query(""), status: str = Query(""),
                          user: dict = Depends(get_current_user)):
    # Admin may view any user's saved jobs via the email query; everyone else is scoped to their own token.
    if email and email.lower() != user["email"].lower() and user["email"].lower() != ADMIN_EMAIL.lower():
        raise HTTPException(status_code=403, detail="Not authorized")
    email = email or user["email"]
    jobs = get_saved_jobs(email, status)
    scores = get_latest_referral_scores(email)
    for j in jobs:
        m = scores.get(j.get("url", ""))
        if m:
            j["match_score"] = m
    return {"jobs": jobs}


@router.get("/check")
async def saved_jobs_check(url: str = Query(""), user: dict = Depends(get_current_user)):
    if not url:
        return {"saved": False}
    saved = is_job_saved(user["email"], url)
    return {"saved": saved}


@router.post("/batch-check")
async def saved_jobs_batch_check(req: BatchCheckRequest, user: dict = Depends(get_current_user)):
    if not req.urls:
        return {"saved_map": {}}
    saved_map = batch_check_saved(user["email"], req.urls)
    return {"saved_map": saved_map}


@router.patch("/{job_id}/status")
async def saved_jobs_update_status(job_id: int, req: UpdateStatusRequest, user: dict = Depends(get_current_user)):
    owner = get_saved_job_owner(job_id)
    if owner and owner.lower() != user["email"].lower() and user["email"].lower() != ADMIN_EMAIL.lower():
        raise HTTPException(status_code=403, detail="Not authorized")
    ok = update_saved_job_status(job_id, req.status)
    return {"ok": ok}


@router.delete("/{job_id}")
async def saved_jobs_delete(job_id: int, user: dict = Depends(get_current_user)):
    owner = get_saved_job_owner(job_id)
    if owner and owner.lower() != user["email"].lower() and user["email"].lower() != ADMIN_EMAIL.lower():
        raise HTTPException(status_code=403, detail="Not authorized")
    ok = delete_saved_job(job_id)
    return {"deleted": ok}
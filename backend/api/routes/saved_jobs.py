from fastapi import APIRouter, Query
from pydantic import BaseModel

from db import add_saved_job, is_job_saved, get_saved_jobs, update_saved_job_status, delete_saved_job, batch_check_saved

router = APIRouter(prefix="/api/saved-jobs", tags=["saved-jobs"])


class SaveJobRequest(BaseModel):
    email: str
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
    email: str
    urls: list[str] = []


@router.post("")
async def saved_jobs_create(req: SaveJobRequest):
    result = add_saved_job(req.email, req.model_dump())
    return result


@router.get("")
async def saved_jobs_list(email: str = Query(""), status: str = Query("")):
    if not email:
        return {"error": "email required"}
    jobs = get_saved_jobs(email, status)
    return {"jobs": jobs}


@router.get("/check")
async def saved_jobs_check(email: str = Query(""), url: str = Query("")):
    if not email or not url:
        return {"saved": False}
    saved = is_job_saved(email, url)
    return {"saved": saved}


@router.post("/batch-check")
async def saved_jobs_batch_check(req: BatchCheckRequest):
    if not req.email or not req.urls:
        return {"saved_map": {}}
    saved_map = batch_check_saved(req.email, req.urls)
    return {"saved_map": saved_map}


@router.patch("/{job_id}/status")
async def saved_jobs_update_status(job_id: int, req: UpdateStatusRequest):
    ok = update_saved_job_status(job_id, req.status)
    return {"ok": ok}


@router.delete("/{job_id}")
async def saved_jobs_delete(job_id: int):
    ok = delete_saved_job(job_id)
    return {"deleted": ok}

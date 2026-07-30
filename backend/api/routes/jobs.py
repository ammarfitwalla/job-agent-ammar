from fastapi import APIRouter, HTTPException, Query
from db import get_raw_jobs

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("")
async def list_jobs(search_id: str = Query(""), site: str = "",
                    experience_level: str = ""):
    if not search_id:
        return {"total": 0, "jobs": []}
    jobs = get_raw_jobs(search_id)
    if site:
        from utils.url_utils import site_from_url
        jobs = [j for j in jobs if site_from_url(j.get("url", "")) == site]
    if experience_level:
        jobs = [j for j in jobs if j.get("experience_level") == experience_level]
    return {"total": len(jobs), "jobs": jobs}


@router.get("/{index}")
async def get_job(search_id: str = Query(""), index: int = 0):
    if not search_id:
        raise HTTPException(404, "Job not found")
    jobs = get_raw_jobs(search_id)
    if index < 0 or index >= len(jobs):
        raise HTTPException(404, "Job not found")
    return jobs[index]

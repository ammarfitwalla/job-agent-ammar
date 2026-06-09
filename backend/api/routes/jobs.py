from fastapi import APIRouter, HTTPException
from api.schemas import Job

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("")
async def list_jobs(min_score: int = 0, site: str = "", experience_level: str = ""):
    from api.main import job_store
    all_jobs = job_store.get("filtered", [])
    print(f"[JOBS] Fetch — {len(all_jobs)} in store, min_score={min_score}, site={site}, experience_level={experience_level}")
    if all_jobs:
        print(f"[JOBS] First job: {all_jobs[0].get('title','?')} score={all_jobs[0].get('total_score','?')}")
    if min_score:
        all_jobs = [j for j in all_jobs if (j.get("total_score") or 0) >= min_score]
    if site:
        all_jobs = [j for j in all_jobs if site.lower() in j.get("url", "").lower()]
    if experience_level:
        all_jobs = [j for j in all_jobs if j.get("experience_level") == experience_level]
    print(f"[JOBS] Returning {len(all_jobs)} jobs")
    return {"total": len(all_jobs), "jobs": all_jobs}


@router.get("/{index}")
async def get_job(index: int):
    from api.main import job_store
    jobs = job_store.get("filtered", [])
    if index < 0 or index >= len(jobs):
        raise HTTPException(404, "Job not found")
    return jobs[index]

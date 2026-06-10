from fastapi import APIRouter, Query
from db import get_filtered_jobs

router = APIRouter(prefix="/email", tags=["email"])


@router.post("/report")
async def send_report(search_id: str = Query("")):
    from utils.emailer import send_remoteok_batch_email

    if not search_id:
        return {"message": "Missing search_id", "sent": False}
    jobs = get_filtered_jobs(search_id)
    if not jobs:
        return {"message": "No jobs to report", "sent": False}

    send_remoteok_batch_email(jobs)
    return {"message": f"Report sent with {len(jobs)} jobs", "sent": True}

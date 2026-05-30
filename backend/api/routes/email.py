from fastapi import APIRouter
from api.schemas import Job

router = APIRouter(prefix="/email", tags=["email"])


@router.post("/report")
async def send_report():
    from api.main import job_store
    from utils.emailer import send_remoteok_batch_email

    jobs = job_store.get("filtered", [])
    if not jobs:
        return {"message": "No jobs to report", "sent": False}

    send_remoteok_batch_email(jobs)
    return {"message": f"Report sent with {len(jobs)} jobs", "sent": True}

from fastapi import APIRouter, Query, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
import os, time

from db import get_user, update_user_name, update_user_profile, get_saved_jobs_status_counts

_RESUME_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "resumes")
os.makedirs(_RESUME_DIR, exist_ok=True)

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
        "resume_filename": user.get("resume_filename", ""),
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


@router.post("/resume")
async def profile_upload_resume(email: str = Query(""), file: UploadFile = File(...)):
    if not email:
        raise HTTPException(400, "email required")
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".pdf", ".docx", ".txt"):
        raise HTTPException(400, "Only PDF, DOCX, and TXT files are supported")
    ts = int(time.time())
    filename = f"resume_{email.split('@')[0]}_{ts}{ext}"
    filepath = os.path.join(_RESUME_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(await file.read())
    update_user_profile(email, resume_filename=filename)
    return {"ok": True, "filename": filename}


@router.get("/resume")
async def profile_download_resume(email: str = Query("")):
    if not email:
        raise HTTPException(400, "email required")
    user = get_user(email)
    if not user or not user.get("resume_filename"):
        raise HTTPException(404, "No resume found")
    filepath = os.path.join(_RESUME_DIR, user["resume_filename"])
    if not os.path.isfile(filepath):
        raise HTTPException(404, "Resume file not found")
    return FileResponse(filepath, filename=user["resume_filename"])

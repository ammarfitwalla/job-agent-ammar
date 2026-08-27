from fastapi import APIRouter, Query, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
import os, time

from db import get_user, update_user_name, update_user_profile, update_user_refer_opt_in, get_saved_jobs_status_counts

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
    refer_opt_in: int | None = None


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
        "refer_opt_in": user.get("refer_opt_in", 0),
        "created_at": user["created_at"],
        "status_counts": status_counts,
    }


@router.put("/name")
async def profile_update_name(req: UpdateNameRequest):
    update_user_name(req.email, req.name)
    return {"ok": True, "email": req.email, "name": req.name}


@router.put("/refer-opt-in")
async def profile_update_refer_opt_in(req: UpdateProfileRequest):
    update_user_refer_opt_in(req.email, bool(req.refer_opt_in))
    return {"ok": True, "refer_opt_in": 1 if req.refer_opt_in else 0}


@router.put("")
async def profile_update(req: UpdateProfileRequest):
    update_user_profile(
        req.email,
        name=req.name,
        company=req.company,
        position=req.position,
        linkedin_url=req.linkedin_url,
    )
    if req.refer_opt_in is not None:
        update_user_refer_opt_in(req.email, bool(req.refer_opt_in))
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
    user = get_user(email)
    old = (user or {}).get("resume_filename", "") if user else ""
    if old and old != filename:
        try:
            old_path = os.path.join(_RESUME_DIR, old)
            if os.path.isfile(old_path):
                os.remove(old_path)
        except OSError:
            pass
    update_user_profile(email, resume_filename=filename)
    return {"ok": True, "filename": filename}


@router.get("/resume/text")
async def profile_resume_text(email: str = Query("")):
    if not email:
        raise HTTPException(400, "email required")
    user = get_user(email)
    if not user or not user.get("resume_filename"):
        raise HTTPException(404, "No resume found")
    filepath = os.path.join(_RESUME_DIR, user["resume_filename"])
    if not os.path.isfile(filepath):
        raise HTTPException(404, "Resume file not found")
    from api.routes.resume import _extract_text
    text = _extract_text(filepath)
    return {"ok": True, "text": text, "filename": user["resume_filename"]}


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

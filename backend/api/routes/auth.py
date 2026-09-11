import random
import string
import os
import shutil
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api.deps import get_current_user

from db import get_user, create_user, save_verification_code, verify_code, get_custom_companies, add_custom_company
from db import update_user_refer_opt_in, set_user_invited_by, credit_invite_bonus
from config import COMPANIES
from utils.client_ip import get_client_ip
from utils.rate_limiter import check_rate_limit
from utils.jwt import create_token

DEV_MODE = False  # Set to True for development mode, False for production

# Public company-list writes — cap per IP.
_ADD_COMPANY_RATE = 5
_ADD_COMPANY_WINDOW = 60

_RESUMES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "resumes")


def _copy_search_resume(search_id: str, email: str):
    local_part = email.split("@")[0]
    sources = []
    from db import get_session
    s = get_session(search_id)
    if s and s.get("resume_filename"):
        sources.append(os.path.join(_RESUMES_DIR, s["resume_filename"]))
    for ext in (".pdf", ".docx", ".txt"):
        sources.append(os.path.join(_RESUMES_DIR, f"{search_id}{ext}"))
    for src in sources:
        if not os.path.isfile(src):
            continue
        ext = os.path.splitext(src)[1]
        dst = os.path.join(_RESUMES_DIR, f"{local_part}{ext}")
        try:
            shutil.copy2(src, dst)
            from db import update_user_profile
            update_user_profile(email, resume_filename=f"{local_part}{ext}")
        except Exception:
            pass
        return

router = APIRouter(prefix="/api/auth", tags=["auth"])


class SendCodeRequest(BaseModel):
    email: str


class VerifyCodeRequest(BaseModel):
    email: str
    code: str


class RegisterRequest(BaseModel):
    email: str
    name: str
    company: str = ""
    position: str = ""
    linkedin_url: str = ""
    search_id: str = ""
    refer_opt_in: int = 0
    invited_by: str = ""


class AddCompanyRequest(BaseModel):
    name: str


@router.post("/send-code")
async def auth_send_code(req: SendCodeRequest):
    if not check_rate_limit(f"send_code:{req.email}", 3, 60):
        return JSONResponse(status_code=429, content={"ok": False, "error": "Too many requests. Try again later."})
    if DEV_MODE:
        return {"ok": True, "code": "123456", "message": "DEV MODE"}
    code = "".join(random.choices(string.digits, k=6))
    expires_at = (datetime.utcnow() + timedelta(minutes=10)).isoformat()
    save_verification_code(req.email, code, expires_at)
    from utils.smtp_sender import send_verification_email
    smtp_ok = send_verification_email(req.email, code)
    if smtp_ok:
        return {"ok": True, "message": "Code sent"}
    return {"ok": True, "code": code, "fallback": True, "message": "Code generated"}


@router.post("/verify-code")
async def auth_verify_code(req: VerifyCodeRequest):
    if not check_rate_limit(f"verify_code:{req.email}", 5, 300):
        return JSONResponse(status_code=429, content={"ok": False, "error": "Too many attempts. Try again later."})
    if DEV_MODE and req.code == "123456":
        user = get_user(req.email)
        if not user:
            name = req.email.split("@")[0]
            user = create_user(req.email, name)
        return {"ok": True, "token": create_token(user["email"]), "user": {"email": user["email"], "name": user["name"], "company": user.get("company", ""), "position": user.get("position", ""), "linkedin_url": user.get("linkedin_url", ""), "referral_credits": user.get("referral_credits", 0), "refer_opt_in": user.get("refer_opt_in", 0)}}
    if not verify_code(req.email, req.code):
        return {"ok": False, "error": "Invalid or expired code"}
    user = get_user(req.email)
    if not user:
        name = req.email.split("@")[0]
        user = create_user(req.email, name)
    return {"ok": True, "token": create_token(user["email"]), "user": {"email": user["email"], "name": user["name"], "company": user.get("company", ""), "position": user.get("position", ""), "linkedin_url": user.get("linkedin_url", ""), "referral_credits": user.get("referral_credits", 0), "refer_opt_in": user.get("refer_opt_in", 0)}}


@router.post("/register")
async def auth_register(req: RegisterRequest, user: dict = Depends(get_current_user)):
    if req.email.strip().lower() != user["email"].lower():
        raise HTTPException(status_code=403, detail="Email does not match the verified session")
    email = user["email"]
    user = get_user(email)
    if user:
        from db import update_user_profile
        update_user_profile(email, name=req.name, company=req.company, position=req.position, linkedin_url=req.linkedin_url)
    else:
        user = create_user(email, req.name, req.company, req.position, req.linkedin_url)

    if req.refer_opt_in:
        update_user_refer_opt_in(email, 1)

    # Invite bonus: new user via /app?ref=<inviter> auto-opts in as a referrer
    # and both the inviter and the invitee get bonus referral credits.
    if req.invited_by and req.invited_by.lower() != email.lower():
        inviter = get_user(req.invited_by)
        if inviter:
            set_user_invited_by(email, req.invited_by)
            credit_invite_bonus(email, 5)
            credit_invite_bonus(req.invited_by, 5)

    user = get_user(email)

    if req.search_id:
        _copy_search_resume(req.search_id, email)

    return {"ok": True, "user": user}


@router.get("/companies")
async def auth_companies():
    custom = get_custom_companies()
    merged = sorted(set(COMPANIES) | set(custom))
    return {"companies": merged}


@router.post("/companies")
async def auth_add_company(req: AddCompanyRequest, request: Request = None):
    client_ip = get_client_ip(request)
    if client_ip and not check_rate_limit(f"add_company:{client_ip}", _ADD_COMPANY_RATE, _ADD_COMPANY_WINDOW):
        return JSONResponse(status_code=429, content={"ok": False, "error": "Too many requests. Try again later."})
    name = req.name.strip()
    if not name:
        return {"ok": False, "error": "Company name is required"}
    if name in COMPANIES:
        return {"ok": False, "error": "Company already exists"}
    ok = add_custom_company(name)
    if ok:
        return {"ok": True, "company": name}
    return {"ok": False, "error": "Company already added"}

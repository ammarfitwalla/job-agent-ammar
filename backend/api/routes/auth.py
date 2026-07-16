import random
import string
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from db import get_user, create_user, save_verification_code, verify_code, get_custom_companies, add_custom_company
from config import COMPANIES
from utils.rate_limiter import check_rate_limit

DEV_MODE = True  # Set to True for development mode, False for production   

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
    return {"ok": True, "code": code, "message": "Code generated"}


@router.post("/verify-code")
async def auth_verify_code(req: VerifyCodeRequest):
    if not check_rate_limit(f"verify_code:{req.email}", 5, 300):
        return JSONResponse(status_code=429, content={"ok": False, "error": "Too many attempts. Try again later."})
    if DEV_MODE and req.code == "123456":
        user = get_user(req.email)
        if not user:
            name = req.email.split("@")[0]
            user = create_user(req.email, name)
        return {"ok": True, "user": {"email": user["email"], "name": user["name"], "company": user.get("company", ""), "position": user.get("position", ""), "linkedin_url": user.get("linkedin_url", ""), "referral_credits": user.get("referral_credits", 0)}}
    if not verify_code(req.email, req.code):
        return {"ok": False, "error": "Invalid or expired code"}
    user = get_user(req.email)
    if not user:
        name = req.email.split("@")[0]
        user = create_user(req.email, name)
    return {"ok": True, "user": {"email": user["email"], "name": user["name"], "company": user.get("company", ""), "position": user.get("position", ""), "linkedin_url": user.get("linkedin_url", ""), "referral_credits": user.get("referral_credits", 0)}}


@router.post("/register")
async def auth_register(req: RegisterRequest):
    user = get_user(req.email)
    if user:
        from db import update_user_profile
        update_user_profile(req.email, name=req.name, company=req.company, position=req.position, linkedin_url=req.linkedin_url)
    else:
        user = create_user(req.email, req.name, req.company, req.position, req.linkedin_url)
    user = get_user(req.email)
    return {"ok": True, "user": user}


@router.get("/companies")
async def auth_companies():
    custom = get_custom_companies()
    merged = sorted(set(COMPANIES) | set(custom))
    return {"companies": merged}


@router.post("/companies")
async def auth_add_company(req: AddCompanyRequest):
    name = req.name.strip()
    if not name:
        return {"ok": False, "error": "Company name is required"}
    if name in COMPANIES:
        return {"ok": False, "error": "Company already exists"}
    ok = add_custom_company(name)
    if ok:
        return {"ok": True, "company": name}
    return {"ok": False, "error": "Company already added"}

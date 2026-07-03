import random
import string
from datetime import datetime, timedelta
from fastapi import APIRouter
from pydantic import BaseModel

from db import get_user, create_user, save_verification_code, verify_code

DEV_MODE = False  # Set to True for development mode, False for production   

router = APIRouter(prefix="/api/auth", tags=["auth"])


class SendCodeRequest(BaseModel):
    email: str


class VerifyCodeRequest(BaseModel):
    email: str
    code: str


@router.post("/send-code")
async def auth_send_code(req: SendCodeRequest):
    if DEV_MODE:
        return {"ok": True, "code": "123456", "message": "DEV MODE"}
    code = "".join(random.choices(string.digits, k=6))
    expires_at = (datetime.utcnow() + timedelta(minutes=10)).isoformat()
    save_verification_code(req.email, code, expires_at)
    return {"ok": True, "code": code, "message": "Code generated"}


@router.post("/verify-code")
async def auth_verify_code(req: VerifyCodeRequest):
    if DEV_MODE and req.code == "123456":
        user = get_user(req.email)
        if not user:
            name = req.email.split("@")[0]
            user = create_user(req.email, name)
        return {"ok": True, "user": {"email": user["email"], "name": user["name"]}}
    if not verify_code(req.email, req.code):
        return {"ok": False, "error": "Invalid or expired code"}
    user = get_user(req.email)
    if not user:
        name = req.email.split("@")[0]
        user = create_user(req.email, name)
    return {"ok": True, "user": {"email": user["email"], "name": user["name"]}}

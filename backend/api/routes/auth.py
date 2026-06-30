import random
import string
from datetime import datetime, timedelta
from fastapi import APIRouter
from pydantic import BaseModel

from db import get_user, create_user, save_verification_code, verify_code
from utils.emailer import send_verification_code

router = APIRouter(prefix="/api/auth", tags=["auth"])


class SendCodeRequest(BaseModel):
    email: str


class VerifyCodeRequest(BaseModel):
    email: str
    code: str


@router.post("/send-code")
async def auth_send_code(req: SendCodeRequest):
    code = "".join(random.choices(string.digits, k=6))
    expires_at = (datetime.utcnow() + timedelta(minutes=10)).isoformat()
    save_verification_code(req.email, code, expires_at)
    try:
        send_verification_code(req.email, code)
    except Exception as e:
        return {"ok": False, "error": f"Failed to send email: {e}"}
    return {"ok": True, "message": "Code sent"}


@router.post("/verify-code")
async def auth_verify_code(req: VerifyCodeRequest):
    if not verify_code(req.email, req.code):
        return {"ok": False, "error": "Invalid or expired code"}
    user = get_user(req.email)
    if not user:
        name = req.email.split("@")[0]
        user = create_user(req.email, name)
    return {"ok": True, "user": {"email": user["email"], "name": user["name"]}}

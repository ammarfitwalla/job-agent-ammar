from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

from fastapi.responses import JSONResponse

from db import (
    create_referral_request, get_incoming_referrals, get_outgoing_referrals,
    update_referral_status, get_referral_request, get_user, confirm_referral,
    get_pending_referral, get_monthly_sent_count,
)
from utils.rate_limiter import check_rate_limit

_MONTHLY_LIMIT = 3

router = APIRouter(prefix="/api/referrals", tags=["referrals"])


class ReferralRequest(BaseModel):
    from_email: str
    to_email: str
    job_url: str = ""
    job_title: str = ""
    company: str = ""
    match_score: int = 0
    message: str = ""


@router.post("/request")
async def referral_create(req: ReferralRequest):
    if not req.from_email or not req.to_email:
        return {"ok": False, "error": "from_email and to_email are required"}
    if not check_rate_limit(f"referral:{req.from_email}", 10, 60):
        return JSONResponse(status_code=429, content={"ok": False, "error": "Too many requests. Try again later."})
    if req.from_email == req.to_email:
        return {"ok": False, "error": "You can't refer yourself"}
    to_user = get_user(req.to_email)
    if not to_user:
        return {"ok": False, "error": "User not found"}
    existing = get_pending_referral(req.from_email, req.to_email, req.job_url)
    if existing:
        return {"ok": False, "error": "You already have a pending request to this person for this job"}
    sent_count = get_monthly_sent_count(req.from_email)
    remaining = max(0, _MONTHLY_LIMIT - sent_count)
    if sent_count >= _MONTHLY_LIMIT:
        return {"ok": False, "error": f"Monthly limit reached ({_MONTHLY_LIMIT}/month). You have 0 remaining requests.", "remaining": 0}
    rid = create_referral_request(
        req.from_email, req.to_email, req.job_url, req.job_title,
        req.company, req.match_score, req.message,
    )
    return {"ok": True, "id": rid, "remaining": remaining - 1}


@router.get("/incoming")
async def referral_incoming(email: str = ""):
    if not email:
        return {"requests": []}
    reqs = get_incoming_referrals(email)
    for r in reqs:
        from_user = get_user(r["from_email"])
        r["from_name"] = from_user["name"] if from_user else "Unknown"
        r["from_linkedin_url"] = from_user.get("linkedin_url", "") if from_user else ""
        r["from_resume_filename"] = from_user.get("resume_filename", "") if from_user else ""
    return {"requests": reqs}


@router.get("/outgoing")
async def referral_outgoing(email: str = ""):
    if not email:
        return {"requests": []}
    reqs = get_outgoing_referrals(email)
    for r in reqs:
        to_user = get_user(r["to_email"])
        r["to_name"] = to_user["name"] if to_user else "Unknown"
    return {"requests": reqs}


class UpdateStatusRequest(BaseModel):
    email: str


@router.put("/{req_id}/accept")
async def referral_accept(req_id: int, body: UpdateStatusRequest):
    req = get_referral_request(req_id)
    if not req:
        return {"ok": False, "error": "Request not found"}
    if req["to_email"] != body.email:
        return {"ok": False, "error": "Not authorized"}
    ok = update_referral_status(req_id, "accepted")
    if ok:
        from_user = get_user(req["from_email"])
        return {
            "ok": True,
            "contact": {
                "email": from_user["email"] if from_user else "Unknown",
                "name": from_user["name"] if from_user else "Unknown",
                "linkedin_url": from_user.get("linkedin_url", "") if from_user else "",
                "resume_filename": from_user.get("resume_filename", "") if from_user else "",
            }
        }
    return {"ok": False, "error": "Failed to update"}


@router.put("/{req_id}/decline")
async def referral_decline(req_id: int, body: UpdateStatusRequest):
    req = get_referral_request(req_id)
    if not req:
        return {"ok": False, "error": "Request not found"}
    if req["to_email"] != body.email:
        return {"ok": False, "error": "Not authorized"}
    ok = update_referral_status(req_id, "declined")
    return {"ok": ok}


@router.put("/{req_id}/complete")
async def referral_complete(req_id: int, body: UpdateStatusRequest):
    result = confirm_referral(req_id, body.email, "receiver")
    if result["ok"]:
        return {
            "ok": True,
            "credits_awarded": result["credits_awarded"],
            "receiver_confirmed": result["receiver_confirmed"],
            "sender_confirmed": result["sender_confirmed"],
        }
    return {"ok": False, "error": result.get("error", "Cannot complete")}


@router.put("/{req_id}/confirm")
async def referral_confirm(req_id: int, body: UpdateStatusRequest):
    result = confirm_referral(req_id, body.email, "sender")
    if result["ok"]:
        return {
            "ok": True,
            "credits_awarded": result["credits_awarded"],
            "receiver_confirmed": result["receiver_confirmed"],
            "sender_confirmed": result["sender_confirmed"],
        }
    return {"ok": False, "error": result.get("error", "Cannot confirm")}


@router.put("/{req_id}/withdraw")
async def referral_withdraw(req_id: int, body: UpdateStatusRequest):
    req = get_referral_request(req_id)
    if not req:
        return {"ok": False, "error": "Request not found"}
    if req["from_email"] != body.email:
        return {"ok": False, "error": "Not authorized"}
    if req["status"] != "pending":
        return {"ok": False, "error": "Can only withdraw pending requests"}
    ok = update_referral_status(req_id, "cancelled")
    return {"ok": ok}


@router.get("/remaining")
async def referral_remaining(email: str = ""):
    if not email:
        return {"remaining": 0, "limit": _MONTHLY_LIMIT}
    sent_count = get_monthly_sent_count(email)
    remaining = max(0, _MONTHLY_LIMIT - sent_count)
    return {"remaining": remaining, "limit": _MONTHLY_LIMIT}

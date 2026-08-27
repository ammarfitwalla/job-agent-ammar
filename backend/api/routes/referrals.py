import hashlib
import os

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

from fastapi.responses import JSONResponse

from db import (
    create_referral_request, get_incoming_referrals, get_outgoing_referrals,
    update_referral_status, get_referral_request, get_user, confirm_referral,
    get_pending_referral, get_monthly_sent_count,
    get_referral_score, upsert_referral_score,
    add_referral_notify, get_referral_notifies,
)
from utils.rate_limiter import check_rate_limit

_MONTHLY_LIMIT = 5

router = APIRouter(prefix="/api/referrals", tags=["referrals"])

_RESUME_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "resumes")


def _resolve_resume_text(email: str, resume_text: str) -> str:
    """Prefer the resume text sent by the frontend; fall back to the user's stored resume file."""
    if resume_text and resume_text.strip():
        return resume_text.strip()
    try:
        user = get_user(email)
        fname = (user or {}).get("resume_filename") or ""
        if fname:
            filepath = os.path.join(_RESUME_DIR, fname)
            if os.path.isfile(filepath):
                from api.routes.resume import _extract_text
                text = _extract_text(filepath)
                if text and text.strip():
                    return text.strip()
    except Exception:
        pass
    return ""


def _score_referral_job(job_title: str, company: str, job_description: str, resume_text: str) -> int:
    """AI score (0-100) of the job against the sender's resume. Returns 0 if it can't be scored."""
    if not resume_text or not job_title:
        return 0
    try:
        from llm.llm_client import LLMClient
        from llm.prompts import relevance_prompt
        from utils.json_parser import extract_json
        prompt = relevance_prompt(job_title, job_description or company or "", tags=None, resume=resume_text)
        for _ in range(2):
            response = LLMClient.chat(prompt, max_tokens=800)
            parsed = extract_json(response)
            if isinstance(parsed, dict) and isinstance(parsed.get("score"), int):
                return max(0, min(100, parsed["score"]))
    except Exception:
        pass
    return 0


def _resume_hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest()


def _get_or_score_referral_job(from_email: str, job_url: str, job_title: str, company: str,
                               job_description: str, resume_text: str) -> int:
    """Reuse a cached AI score for (user, job, resume); otherwise score via LLM and cache it."""
    resume_text = _resolve_resume_text(from_email, resume_text)
    h = _resume_hash(resume_text)
    if from_email and job_url and h:
        row = get_referral_score(from_email, job_url, h)
        if row and row.get("score"):
            return int(row["score"])
    score = _score_referral_job(job_title, company, job_description, resume_text)
    if from_email and job_url and h and score > 0:
        try:
            upsert_referral_score(from_email, job_url, h, score)
        except Exception:
            pass
    return score


class ReferralRequest(BaseModel):
    from_email: str
    to_email: str
    job_url: str = ""
    job_title: str = ""
    company: str = ""
    match_score: int = 0
    message: str = ""
    job_description: str = ""
    resume_text: str = ""


class ReferralScoreRequest(BaseModel):
    from_email: str
    job_url: str = ""
    job_title: str = ""
    company: str = ""
    job_description: str = ""
    resume_text: str = ""


@router.post("/score")
async def referral_score(req: ReferralScoreRequest):
    score = _get_or_score_referral_job(req.from_email, req.job_url, req.job_title, req.company,
                                       req.job_description, req.resume_text)
    return {"ok": True, "score": score}


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
    existing = get_pending_referral(req.from_email, req.to_email, req.job_url, req.company)
    if existing:
        return {"ok": False, "error": "You already have a pending request to this person for this job"}
    sent_count = get_monthly_sent_count(req.from_email)
    remaining = max(0, _MONTHLY_LIMIT - sent_count)
    if sent_count >= _MONTHLY_LIMIT:
        return {"ok": False, "error": f"Monthly limit reached ({_MONTHLY_LIMIT}/month). You have 0 remaining requests.", "remaining": 0}
    match_score = req.match_score
    if match_score <= 0:
        match_score = _get_or_score_referral_job(req.from_email, req.job_url, req.job_title, req.company,
                                                 req.job_description, req.resume_text)
    rid = create_referral_request(
        req.from_email, req.to_email, req.job_url, req.job_title,
        req.company, match_score, req.message,
    )
    return {"ok": True, "id": rid, "remaining": remaining - 1, "match_score": match_score}


@router.get("/incoming")
async def referral_incoming(email: str = ""):
    if not email:
        return {"requests": []}
    reqs = get_incoming_referrals(email)
    for r in reqs:
        from_user = get_user(r["from_email"])
        r["from_name"] = from_user["name"] if from_user else "Unknown"
        r["from_company"] = from_user.get("company", "") if from_user else ""
        r["from_position"] = from_user.get("position", "") if from_user else ""
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
        r["to_linkedin_url"] = to_user.get("linkedin_url", "") if to_user else ""
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


class NotifyRequest(BaseModel):
    email: str
    company: str = ""


@router.post("/notify")
async def referral_notify(req: NotifyRequest):
    if not req.email or not req.company:
        return {"ok": False, "error": "email and company are required"}
    if not check_rate_limit(f"referral_notify:{req.email}", 5, 60):
        return JSONResponse(status_code=429, content={"ok": False, "error": "Too many requests. Try again later."})
    added = add_referral_notify(req.email.strip(), req.company.strip())
    return {"ok": True, "new": added}


class InviteRequest(BaseModel):
    email: str
    company: str = ""


@router.post("/invite")
async def referral_invite(req: InviteRequest):
    """Generate a shareable invite link that auto-opts the invitee in as a referrer."""
    if not req.email:
        return {"ok": False, "error": "email is required"}
    user = get_user(req.email)
    if not user:
        return {"ok": False, "error": "User not found"}
    base = "/app?ref="
    link = f"{base}{req.email}"
    if req.company:
        link += f"&company={req.company}"
    return {"ok": True, "link": link, "from_email": req.email}


@router.get("/notifies")
async def referral_notifies_list(company: str = ""):
    return {"notifies": get_referral_notifies(company=company)}

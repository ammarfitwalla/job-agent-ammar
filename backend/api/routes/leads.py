from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

from utils.client_ip import get_client_ip
from utils.rate_limiter import check_rate_limit

router = APIRouter(prefix="/api", tags=["leads"])

# Public lead-capture form — cap per IP to prevent DB fill.
_LEAD_RATE = 5
_LEAD_WINDOW = 60


class LeadRequest(BaseModel):
    session_id: Optional[str] = None
    email: str
    name: Optional[str] = ""
    roles: Optional[list] = None
    location: Optional[str] = ""
    keywords: Optional[list] = None
    internship_mode: bool = False
    resume_snippet: Optional[str] = ""


@router.post("/lead")
async def create_lead(req: LeadRequest, request: Request = None):
    client_ip = get_client_ip(request)
    if client_ip and not check_rate_limit(f"lead:{client_ip}", _LEAD_RATE, _LEAD_WINDOW):
        raise HTTPException(429, "Too many requests. Try again later.")
    from email_validator import validate_email, EmailNotValidError

    try:
        validate_email(req.email, check_deliverability=False)
    except EmailNotValidError as e:
        raise HTTPException(status_code=422, detail=str(e))

    from db import add_lead

    lead_id = add_lead(
        session_id=req.session_id,
        email=req.email,
        name=req.name or "",
        roles=req.roles or [],
        location=req.location or "",
        keywords=req.keywords or [],
        internship_mode=req.internship_mode,
        resume_snippet=req.resume_snippet or "",
        source="web",
    )
    return {"ok": True, "id": lead_id}


@router.get("/leads")
async def list_leads(limit: int = 100):
    from db import get_leads

    return {"leads": get_leads(limit=limit)}

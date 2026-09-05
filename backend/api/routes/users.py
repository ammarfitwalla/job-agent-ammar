from fastapi import APIRouter, Query, Request, HTTPException

from db import get_anonymous_referrers_by_company, get_company_referrer_counts, get_company_directory
from utils.rate_limiter import check_rate_limit

router = APIRouter(prefix="/api/users", tags=["users"])

# Referrer lookups are rate-limited per IP to discourage enumeration/bots.
_AT_COMPANY_RATE = 30
_AT_COMPANY_WINDOW = 60


@router.get("/at-company")
async def users_at_company(company: str = Query(""), request: Request = None):
    if not company:
        return {"users": [], "count": 0}
    client_ip = request.client.host if request else ""
    if client_ip and not check_rate_limit(f"users_at_company:{client_ip}", _AT_COMPANY_RATE, _AT_COMPANY_WINDOW):
        raise HTTPException(429, "Too many requests. Try again later.")
    # Privacy: return only an opaque id + position (no email/name/linkedin_url).
    users = get_anonymous_referrers_by_company(company)
    return {"users": users, "count": len(users)}


@router.get("/company-counts")
async def company_counts(companies: str = Query(""), user_email: str = Query("")):
    if not companies:
        return {"counts": {}}
    company_list = [c.strip() for c in companies.split(",") if c.strip()]
    counts = get_company_referrer_counts(company_list, exclude_email=user_email or None)
    return {"counts": {c: counts.get(c.lower(), 0) for c in company_list}}


@router.get("/referrer-directory")
async def referrer_directory(limit: int = Query(100, ge=1, le=500)):
    return {"companies": get_company_directory(limit=limit)}

from fastapi import APIRouter, Query
from db import get_referrers_by_company, get_company_referrer_counts, get_company_directory

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("/at-company")
async def users_at_company(company: str = Query("")):
    if not company:
        return {"users": []}
    users = get_referrers_by_company(company)
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

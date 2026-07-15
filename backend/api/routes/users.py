from fastapi import APIRouter, Query
from db import get_users_by_company

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("/at-company")
async def users_at_company(company: str = Query("")):
    if not company:
        return {"users": []}
    users = get_users_by_company(company)
    return {"users": users, "count": len(users)}

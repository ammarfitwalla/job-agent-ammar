from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
import asyncio

from utils.client_ip import get_client_ip
from utils.rate_limiter import check_rate_limit

router = APIRouter(prefix="/api/visit", tags=["visits"])

# Heartbeat writes — cap per IP to prevent DB growth spam (generous vs real pings).
_VISIT_RATE = 120
_VISIT_WINDOW = 60


class VisitStart(BaseModel):
    visit_id: str
    device_type: str = "unknown"
    path: str = "/"
    referer: str = ""
    session_id: str = ""
    user_email: str = ""


class VisitPing(BaseModel):
    visit_id: str
    elapsed_seconds: float = 0


class VisitEnd(BaseModel):
    visit_id: str
    total_duration: float = 0


@router.post("/start")
async def visit_start(body: VisitStart, request: Request):
    client_ip = get_client_ip(request)
    if client_ip and not check_rate_limit(f"visit:{client_ip}", _VISIT_RATE, _VISIT_WINDOW):
        raise HTTPException(429, "Too many requests. Try again later.")
    from db import log_visit_start, _store_geo

    ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    if not ip:
        ip = request.client.host if request.client else "unknown"
    ua = request.headers.get("user-agent", "")
    log_visit_start(
        visit_id=body.visit_id,
        ip_address=ip,
        user_agent=ua,
        device_type=body.device_type,
        referer=body.referer,
        path=body.path,
        session_id=body.session_id,
        user_email=body.user_email,
    )
    asyncio.create_task(asyncio.to_thread(_store_geo, ip, body.visit_id))
    return {"ok": True}


@router.post("/ping")
async def visit_ping(body: VisitPing, request: Request = None):
    client_ip = get_client_ip(request)
    if client_ip and not check_rate_limit(f"visit:{client_ip}", _VISIT_RATE, _VISIT_WINDOW):
        raise HTTPException(429, "Too many requests. Try again later.")
    from db import update_visit_ping

    update_visit_ping(body.visit_id, body.elapsed_seconds)
    return {"ok": True}


@router.post("/end")
async def visit_end(body: VisitEnd, request: Request = None):
    client_ip = get_client_ip(request)
    if client_ip and not check_rate_limit(f"visit:{client_ip}", _VISIT_RATE, _VISIT_WINDOW):
        raise HTTPException(429, "Too many requests. Try again later.")
    from db import finalize_visit

    finalize_visit(body.visit_id, body.total_duration)
    return {"ok": True}

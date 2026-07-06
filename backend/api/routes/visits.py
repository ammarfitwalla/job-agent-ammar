from fastapi import APIRouter, Request
from pydantic import BaseModel
import asyncio

router = APIRouter(prefix="/api/visit", tags=["visits"])


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
async def visit_ping(body: VisitPing):
    from db import update_visit_ping

    update_visit_ping(body.visit_id, body.elapsed_seconds)
    return {"ok": True}


@router.post("/end")
async def visit_end(body: VisitEnd):
    from db import finalize_visit

    finalize_visit(body.visit_id, body.total_duration)
    return {"ok": True}

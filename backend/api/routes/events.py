from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import Optional

from utils.client_ip import get_client_ip
from utils.rate_limiter import check_rate_limit

router = APIRouter(prefix="/api/events", tags=["events"])

# Beacon log — cap per IP to prevent DB growth spam (generous vs real usage).
_EVENT_RATE = 120
_EVENT_WINDOW = 60


class EventRequest(BaseModel):
    session_id: str
    event: str
    data: Optional[dict] = None
    elapsed: int = 0


@router.post("")
async def log_event(req: EventRequest, request: Request = None):
    client_ip = get_client_ip(request)
    if client_ip and not check_rate_limit(f"events:{client_ip}", _EVENT_RATE, _EVENT_WINDOW):
        raise HTTPException(429, "Too many requests. Try again later.")
    from db import add_event
    add_event(req.session_id, req.event, req.data or {}, req.elapsed)
    return {"ok": True}

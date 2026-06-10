from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/api/events", tags=["events"])


class EventRequest(BaseModel):
    session_id: str
    event: str
    data: Optional[dict] = None
    elapsed: int = 0


@router.post("")
async def log_event(req: EventRequest):
    from db import add_event
    add_event(req.session_id, req.event, req.data or {}, req.elapsed)
    return {"ok": True}

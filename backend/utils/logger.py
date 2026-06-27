import time
from datetime import datetime

def log(message: str, sid: str = None):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {message}")
    if sid:
        from db import add_event, get_session
        s = get_session(sid)
        elapsed = 0
        if s and s.get("created_at"):
            elapsed = int((datetime.utcnow() - datetime.fromisoformat(s["created_at"])).total_seconds())
        add_event(sid, message, elapsed=elapsed)

import time

def log(message: str, sid: str = None):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {message}")
    if sid:
        from db import add_event
        add_event(sid, message)

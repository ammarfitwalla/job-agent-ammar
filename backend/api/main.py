# FastAPI entry point
import sys
import os

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.routing import Mount
from api.routes import jobs, scrape, email, resume, roles, states, events, leads, admin, auth, profile, saved_jobs, visits
import json
from db import init_db

VOTE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "votes.json")
VOTE_THRESHOLD = 100

def _load_votes() -> int:
    if os.path.isfile(VOTE_FILE):
        try:
            with open(VOTE_FILE) as f:
                return json.load(f).get("votes", 0)
        except: pass
    return 0

def _save_votes(count: int):
    with open(VOTE_FILE, "w") as f:
        json.dump({"votes": count}, f)

app = FastAPI(
    title="Job Agent API",
    description="Scrape, score, and manage job applications",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Visit logging is handled client-side via the frontend beacon (/api/visit/start, /api/visit/end)
# which captures device type, duration, path, and referer accurately.


app.include_router(jobs.router)
app.include_router(scrape.router)
app.include_router(email.router)
app.include_router(resume.router)
app.include_router(roles.router)
app.include_router(states.router)
app.include_router(events.router)
app.include_router(leads.router)
app.include_router(admin.router)
app.include_router(auth.router)
app.include_router(profile.router)
app.include_router(saved_jobs.router)
app.include_router(visits.router)


@app.on_event("startup")
async def startup():
    init_db()
    from marketing.scheduler import start_scheduler
    start_scheduler()


@app.get("/votes")
async def get_votes():
    count = _load_votes()
    return {"votes": count, "threshold": VOTE_THRESHOLD}

@app.post("/vote")
async def cast_vote():
    count = _load_votes() + 1
    _save_votes(count)
    return {"votes": count, "threshold": VOTE_THRESHOLD}

@app.delete("/votes")
async def reset_votes():
    if os.path.isfile(VOTE_FILE):
        os.remove(VOTE_FILE)
    return {"votes": 0, "threshold": VOTE_THRESHOLD, "message": "Votes reset"}

@app.get("/health")
async def health():
    from api.schemas import HealthResponse

    scrapers = ["adzuna", "remoteok", "indeed"]
    return HealthResponse(status="ok", scrapers_configured=scrapers)


@app.get("/logs")
async def view_logs():
    from db import get_visits
    visits = get_visits(limit=500)
    lines = ["timestamp | ip | location | path | device | duration"]
    for v in visits:
        loc = ", ".join(filter(None, [v.get("country", ""), v.get("region", ""), v.get("city", "")])) or "-"
        lines.append(f"{v['created_at']} | {v['ip_address']} | {loc} | {v['path']} | {v['device_type']} | {v['duration_seconds']}s")
    return PlainTextResponse("\n".join(lines) if lines else "(no visits yet)")


# Admin dashboard redirect
_frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "frontend")
_admin_html = os.path.join(_frontend_dir, "admin.html")


@app.get("/admin")
async def admin_redirect():
    if os.path.isfile(_admin_html):
        return FileResponse(_admin_html)
    return PlainTextResponse("admin.html not found", status_code=404)


# Serve frontend (must be last — catches all unmatched routes)


@app.get("/db")
async def download_db():
    from db import _DB_PATH
    if os.path.isfile(_DB_PATH):
        return FileResponse(_DB_PATH, filename="job_agent.db", media_type="application/octet-stream")
    return PlainTextResponse("Database not found", status_code=404)
if os.path.isdir(_frontend_dir):
    app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")

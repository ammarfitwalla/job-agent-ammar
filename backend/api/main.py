# FastAPI entry point
import sys
import os

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.routing import Mount
from api.routes import jobs, scrape, email, resume, roles, states
import json

# In-memory job store (lives as long as the server runs)
job_store: dict = {"raw": [], "filtered": [], "internship_mode": False}

VOTE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "votes.json")
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


@app.middleware("http")
async def log_visitors(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path not in ("/health", "/logs", "/favicon.ico") and not path.startswith("/static") and not path.startswith("/api"):
        from utils.visitor_log import log_visitor
        ip = request.client.host if request.client else "unknown"
        ua = request.headers.get("user-agent", "")
        ref = request.headers.get("referer", "")
        log_visitor(ip, path, ua, ref)
    return response


app.include_router(jobs.router)
app.include_router(scrape.router)
app.include_router(email.router)
app.include_router(resume.router)
app.include_router(roles.router)
app.include_router(states.router)


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
    from utils.visitor_log import LOG_FILE
    if os.path.isfile(LOG_FILE):
        with open(LOG_FILE, encoding="utf-8") as f:
            return PlainTextResponse(f.read())
    return PlainTextResponse("(no visitors yet)")


# Serve frontend (must be last — catches all unmatched routes)
_frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "frontend")
if os.path.isdir(_frontend_dir):
    app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")

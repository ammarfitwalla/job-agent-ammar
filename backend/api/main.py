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
from api.routes import jobs, scrape, email, resume, roles

# In-memory job store (lives as long as the server runs)
job_store: dict = {"raw": [], "filtered": []}

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


@app.get("/health")
async def health():
    from api.schemas import HealthResponse

    scrapers = ["adzuna", "remoteok"]
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

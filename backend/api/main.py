# FastAPI entry point
import sys
import os

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
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

app.include_router(jobs.router)
app.include_router(scrape.router)
app.include_router(email.router)
app.include_router(resume.router)
app.include_router(roles.router)


@app.get("/health")
async def health():
    from api.schemas import HealthResponse

    scrapers = ["remoteok_scraper", "weworkremotely_scraper"]
    return HealthResponse(status="ok", scrapers_configured=scrapers)


# Serve frontend (must be last — catches all unmatched routes)
_frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "frontend")
if os.path.isdir(_frontend_dir):
    app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")

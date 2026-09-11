# FastAPI entry point
import sys
import os
from contextlib import asynccontextmanager

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from api.routes import jobs, scrape, resume, roles, states, events, leads, admin, auth, profile, saved_jobs, visits, users, referrals, stats, joblink
import json
from db import init_db
from config import ADMIN_EMAIL, JWT_ALLOW_DEV_SECRET
from utils.jwt import JwtError, decode_token, ensure_secret

VOTE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "votes.json")
VOTE_THRESHOLD = 100


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        ensure_secret()
    except JwtError as e:
        raise RuntimeError(
            f"JWT misconfiguration at startup: {e}. Set JWT_SECRET (no random in-process fallback)."
        ) from e
    init_db()
    try:
        from scheduler import start_scheduler
        start_scheduler()
    except Exception as e:
        import traceback
        traceback.print_exc()
    yield
    try:
        from scheduler import shutdown_scheduler
        shutdown_scheduler()
    except Exception:
        pass


def _load_votes() -> int:
    if os.path.isfile(VOTE_FILE):
        try:
            with open(VOTE_FILE) as f:
                return json.load(f).get("votes", 0)
        except Exception: pass
    return 0

def _save_votes(count: int):
    with open(VOTE_FILE, "w") as f:
        json.dump({"votes": count}, f)

app = FastAPI(
    title="JobAwn API",
    description="Scrape, score, and manage job applications",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Force revalidation for the HTML/JS/CSS so deployed frontend changes
# reach users without manual ?v= cache-busting bumps.
@app.middleware("http")
async def no_cache_frontend(request, call_next):
    response = await call_next(request)
    path = request.url.path
    if (
        path.startswith("/js/")
        or path.endswith(".css")
        or path.endswith(".html")
        or path in ("/", "/app", "/admin", "/profile")
    ):
        response.headers["Cache-Control"] = "no-cache"
    return response


# ==============
# AUTH GUARD
# Default-deny for /api/* (except the public whitelist), admin-class paths
# require a token whose email equals the admin email (case-insensitive),
# and legacy admin surfaces (/db, /logs, /docs, /redoc, /openapi.json,
# /resume/download, /resume/storage) require the same. OPTIONS preflights pass.
# ==============
_STATIC_EXT = (".html", ".css", ".js", ".png", ".svg", ".ico", ".webp", ".jpg",
               ".jpeg", ".gif", ".woff", ".woff2", ".txt", ".map")
_PUBLIC_PATHS = {"/", "/app", "/profile", "/admin", "/health"}
_PUBLIC_PREFIXES = ("/js/", "/css/", "/images/", "/fonts/")
_PUBLIC_EXACT_API = {
    "/api/stats/public",
    "/api/auth/send-code",
    "/api/auth/verify-code",
    "/api/lead",
    "/api/events",
    "/api/referrals/resolve-url",
    "/api/users/at-company",
    "/api/users/company-counts",
    "/api/users/referrer-directory",
}
_PUBLIC_GET_ONLY = {"/api/auth/companies"}
_PUBLIC_NON_API = {"/scrape", "/scrape/stop", "/scrape/status", "/states", "/roles", "/jobs"}
_PUBLIC_PREFIX_API = ("/api/visit/",)

_ADMIN_PATHS = {
    "/db", "/logs", "/docs", "/redoc", "/openapi.json",
    "/resume/download", "/resume/storage",
    "/api/leads",
    "/api/referrals/notifies",
}
_ADMIN_METHOD_PATHS = {("DELETE", "/votes")}
_ADMIN_PREFIXES = ("/api/admin/",)

_PROTECTED_NON_API = {"/roles/custom"}

# Interaction with the live API docs requires an admin token everywhere except local dev,
# where JWT_ALLOW_DEV_SECRET=1 also flips the docs open (FastAPI /docs, /redoc, /openapi.json).
_DEV_DOC_PUBLIC = JWT_ALLOW_DEV_SECRET
_DEV_DOC_PATHS = ("/docs", "/redoc", "/openapi.json")


def _is_admin_class(method: str, path: str) -> bool:
    if _DEV_DOC_PUBLIC and path in _DEV_DOC_PATHS:
        return False
    if path.startswith(_ADMIN_PREFIXES):
        return True
    if path in _ADMIN_PATHS:
        return True
    if (method, path) in _ADMIN_METHOD_PATHS:
        return True
    return False


def _is_public(method: str, path: str) -> bool:
    if _DEV_DOC_PUBLIC and path in _DEV_DOC_PATHS:
        return True
    if path in _PUBLIC_PATHS:
        return True
    if path.startswith(_PUBLIC_PREFIXES):
        return True
    if path.endswith(_STATIC_EXT) and not path.endswith(".json"):
        return True
    if path in _PUBLIC_EXACT_API:
        return True
    if path in _PUBLIC_GET_ONLY and method == "GET":
        return True
    if path.startswith(_PUBLIC_PREFIX_API):
        return True
    if path in _PUBLIC_NON_API and not (path == "/votes" and method == "DELETE"):
        return True
    return False


@app.middleware("http")
async def auth_guard(request: Request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)

    path = request.url.path
    user = None
    auth_header = request.headers.get("authorization", "")
    if auth_header:
        scheme, _, token = auth_header.partition(" ")
        if scheme.lower() == "bearer" and token.strip():
            try:
                payload = decode_token(token.strip())
                sub = (payload.get("sub") or "").strip()
                if sub:
                    user = {"email": sub}
            except JwtError:
                user = None
    request.state.user = user

    if _is_admin_class(request.method, path):
        if not user:
            return JSONResponse(status_code=401, content={"detail": "Invalid or missing credentials"})
        if user["email"].lower() != ADMIN_EMAIL.lower():
            return JSONResponse(status_code=403, content={"detail": "Not authorized"})
        return await call_next(request)

    if _is_public(request.method, path):
        return await call_next(request)

    if path.startswith("/api/") or path in _PROTECTED_NON_API:
        if not user:
            return JSONResponse(status_code=401, content={"detail": "Invalid or missing credentials"})

    return await call_next(request)


# Visit logging is handled client-side via the frontend beacon (/api/visit/start, /api/visit/end)
# which captures device type, duration, path, and referer accurately.


app.include_router(jobs.router)
app.include_router(scrape.router)
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
app.include_router(users.router)
app.include_router(referrals.router)
app.include_router(joblink.router)
app.include_router(stats.router)


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
_landing_html = os.path.join(_frontend_dir, "landing.html")
_app_html = os.path.join(_frontend_dir, "index.html")
_profile_html = os.path.join(_frontend_dir, "profile.html")


@app.get("/admin")
async def admin_redirect():
    if os.path.isfile(_admin_html):
        return FileResponse(_admin_html)
    return PlainTextResponse("admin.html not found", status_code=404)


@app.get("/app")
async def app_redirect():
    if os.path.isfile(_app_html):
        return FileResponse(_app_html)
    return PlainTextResponse("index.html not found", status_code=404)


@app.get("/profile")
async def profile_redirect():
    if os.path.isfile(_profile_html):
        return FileResponse(_profile_html)
    return PlainTextResponse("profile.html not found", status_code=404)


@app.get("/")
async def landing_page():
    if os.path.isfile(_landing_html):
        return FileResponse(_landing_html)
    return PlainTextResponse("landing.html not found", status_code=404)


# Serve frontend (must be last — catches all unmatched routes)


@app.get("/db")
async def download_db():
    from db import _DB_PATH, _get_conn
    if os.path.isfile(_DB_PATH):
        with _get_conn() as (conn, cur):
            cur.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return FileResponse(_DB_PATH, filename="job_agent.db", media_type="application/octet-stream")
    return PlainTextResponse("Database not found", status_code=404)
if os.path.isdir(_frontend_dir):
    app.mount("/", StaticFiles(directory=_frontend_dir), name="frontend")

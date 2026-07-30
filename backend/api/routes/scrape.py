import os
import threading
from typing import Optional
from datetime import datetime, timedelta
from fastapi import APIRouter, Query
from api.schemas import ScrapeRequest
from utils.logger import log
from db import create_session, update_session, get_session, set_raw_jobs, get_events, _get_conn

router = APIRouter(prefix="/scrape", tags=["scrape"])

_STALE_TIMEOUT_MINUTES = 15


def cancel_stale_sessions():
    from db import _get_conn
    cutoff = (datetime.utcnow() - timedelta(minutes=_STALE_TIMEOUT_MINUTES)).isoformat()
    try:
        with _get_conn() as (conn, cur):
            cur.execute("SELECT id FROM sessions WHERE status = 'running' AND updated_at < ?", (cutoff,))
            stale = [row[0] for row in cur.fetchall()]
        for sid in stale:
            log(f"[GC] Cancelling stale session {sid}", sid)
            try:
                update_session(sid, cancel=True, status="done")
            except Exception as inner:
                log(f"[GC] Failed to cancel {sid}: {inner}")
    except Exception as e:
        log(f"[GC] Error cancelling stale sessions: {e}")


def _start_stale_cleanup():
    def _loop():
        while True:
            threading.Event().wait(60)
            cancel_stale_sessions()
    t = threading.Thread(target=_loop, daemon=True)
    t.start()


_start_stale_cleanup()


def _save_elapsed(sid):
    s = get_session(sid)
    if s and s.get("created_at"):
        elapsed = (datetime.utcnow() - datetime.fromisoformat(s["created_at"])).total_seconds()
        update_session(sid, elapsed_seconds=round(elapsed, 1))


def _harvest_companies(jobs: list):
    from config import COMPANIES
    from db import batch_add_custom_companies

    seen = set()
    companies = []
    for job in jobs:
        company = job.get("company", "").strip()
        if company and company not in seen:
            seen.add(company)
            if company not in COMPANIES:
                companies.append(company)
    if companies:
        batch_add_custom_companies(companies)


SITE_MAP = {
    "remoteok": ("remoteok_scraper", "scrape_remoteok"),
    "adzuna": ("adzuna_scraper", "scrape_adzuna"),
    "indeed": ("indeed_scraper", "scrape_indeed"),
    "linkedin": ("linkedin_scraper", "scrape_linkedin"),
    "weworkremotely": ("weworkremotely_scraper", "scrape_wwr"),
    "naukri": ("naukri_scraper", "scrape_naukri"),
    "gulftalent": ("gulftalent_scraper", "scrape_gulftalent"),
    "eurojobs": ("eurojobs_scraper", "scrape_eurojobs"),
}


def _is_cancelled(sid: str) -> bool:
    s = get_session(sid)
    return bool(s and s.get("cancel"))


def run_scrape(sid, sites, roles, location, adzuna_country, indeed_country,
               keywords=None, internship_mode=False, user_email="", scrape_limit=200):
    import importlib
    from match_engine.relevance_engine import keyword_score as _kw_score, role_match_count as _role_match

    create_session(sid, sites=sites, keywords=keywords or [], roles=roles or [])
    update_session(sid, status="running", cancel=False)

    all_jobs = []

    for site_key in sites:
        s = get_session(sid)
        if s and s.get("cancel"):
            log(f"[SCRAPE] Cancelled by user", sid)
            update_session(sid, status="done")
            return

        module_name, func_name = SITE_MAP.get(site_key, (None, None))
        if not module_name:
            log(f"[SCRAPE] Unknown site: {site_key}", sid)
            continue
        try:
            log(f"[SCRAPE] Running {site_key}...", sid)
            mod = importlib.import_module(f"scrapers.{module_name}")
            scraper_fn = getattr(mod, func_name)
            try:
                kwargs = {"roles": roles}
                if site_key == "adzuna":
                    kwargs["country"] = adzuna_country
                    kwargs["internship_mode"] = internship_mode
                if site_key in ("indeed", "linkedin"):
                    kwargs["location"] = location or "United States"
                    kwargs["results_wanted"] = scrape_limit
                    kwargs["internship_mode"] = internship_mode
                if site_key == "indeed":
                    kwargs["country_indeed"] = indeed_country
                jobs = scraper_fn(**kwargs)
            except TypeError:
                jobs = scraper_fn()
            log(f"[SCRAPE] {site_key} returned {len(jobs)} jobs", sid)
            all_jobs.extend(jobs)
            from utils.delay import delay as _rd
            _rd(3, 6)
        except Exception as e:
            log(f"[SCRAPE] {site_key} failed: {e}", sid)

    log(f"[SCRAPE] Total raw jobs: {len(all_jobs)}", sid)
    update_session(sid, scraped=len(all_jobs))
    _harvest_companies(all_jobs)

    if not all_jobs:
        log(f"[SCRAPE] No jobs found", sid)
        from db import set_raw_jobs as _set_raw
        _set_raw(sid, [])
        _save_elapsed(sid)
        update_session(sid, status="done")
        return

    # Filter by title relevance to role
    before_count = len(all_jobs)
    all_jobs = [j for j in all_jobs if _role_match(j.get("title", ""), roles) > 0]
    dropped = before_count - len(all_jobs)
    if dropped:
        log(f"[SCRAPE] Title filter: {before_count} → {len(all_jobs)} (dropped {dropped} irrelevant)", sid)

    # In internship mode, drop senior/mid-level jobs
    if internship_mode:
        from utils.experience_level import detect_experience_level
        before_exp = len(all_jobs)
        for job in all_jobs:
            if "experience_level" not in job:
                job["experience_level"] = detect_experience_level(
                    job.get("title", ""), job.get("description", "")
                )
        all_jobs = [
            j for j in all_jobs
            if j.get("experience_level") in ("internship", "entry_level")
        ]
        dropped_exp = before_exp - len(all_jobs)
        if dropped_exp:
            log(f"[SCRAPE] Internship filter: {before_exp} → {len(all_jobs)} (dropped {dropped_exp} senior/mid-level)", sid)

    # Keyword sort
    from db import set_raw_jobs as _set_raw
    for job in all_jobs:
        job["keyword_score"] = _kw_score(
            job.get("title", ""),
            job.get("description", ""),
            job.get("tags", []),
            keywords=keywords or [],
        )
    all_jobs.sort(key=lambda j: j.get("keyword_score", 0), reverse=True)

    _set_raw(sid, all_jobs)
    _save_elapsed(sid)
    update_session(sid, status="done")
    log(f"[SCRAPE] Pipeline complete — {len(all_jobs)} raw jobs stored", sid)


@router.post("")
async def trigger_scrape(req: ScrapeRequest):
    if not req.search_id:
        return {"message": "Missing search_id", "status": "error"}
    sid = req.search_id
    log(f"[SCRAPE] Search triggered — sites={req.sites}, "
          f"mode={'internship' if req.internship_mode else 'normal'}", sid)
    t = threading.Thread(target=run_scrape, args=(
        sid, req.sites, req.roles, req.location, req.adzuna_country, req.indeed_country,
    ), kwargs={
        "keywords": req.keywords,
        "internship_mode": req.internship_mode,
        "user_email": req.user_email,
        "scrape_limit": req.scrape_limit,
    }, daemon=True)
    t.start()
    return {"message": "Scrape started", "status": "running"}


@router.post("/stop")
async def stop_scrape(search_id: str = Query("")):
    if not search_id:
        return {"message": "Missing search_id", "status": "error"}
    log(f"[STOP] Stop requested for session {search_id}", search_id)
    update_session(search_id, cancel=True, status="done")
    return {"message": "Scrape cancelled", "status": "done"}


@router.get("/status")
async def scrape_status(search_id: str = Query("")):
    if not search_id:
        return {"status": "idle", "last_scrape_raw": 0, "queue_position": 0}
    s = get_session(search_id)
    if s is None:
        return {"status": "idle", "last_scrape_raw": 0, "queue_position": 0}
    from db import count_raw_jobs as _count_raw
    raw_count = _count_raw(search_id)
    return {
        "status": s.get("status", "idle"),
        "last_scrape_raw": s.get("scraped") or 0,
        "last_scrape_relevant": raw_count,
        "queue_position": s.get("queue_position", 0),
        "elapsed": s.get("elapsed_seconds", 0),
        "logs": get_events(search_id, limit=50),
    }

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
    "indeed": ("indeed_scraper", "scrape_indeed"),
    "linkedin": ("linkedin_scraper", "scrape_linkedin"),
}


def _is_cancelled(sid: str) -> bool:
    s = get_session(sid)
    return bool(s and s.get("cancel"))


def run_scrape(sid, sites, roles, location, indeed_country,
               keywords=None, internship_mode=False, user_email="", resume_filename="", scrape_limit=200,
               hours_old=168):
    import importlib
    from match_engine.relevance_engine import keyword_score as _kw_score, role_match_count as _role_match
    from utils.delay import delay as _delay
    from db import set_raw_jobs as _set_raw
    from utils.experience_level import detect_experience_level

    create_session(sid, sites=sites, keywords=keywords or [], roles=roles or [], user_email=user_email,
                   location=location or "")
    from db import get_user as _get_user
    session_resume = resume_filename or ""
    if not session_resume and user_email:
        u = _get_user(user_email)
        session_resume = (u or {}).get("resume_filename") or ""
    update_session(sid, status="running", cancel=False, resume_filename=session_resume)

    all_jobs = []
    seen_urls = set()
    combo_index = 0
    total_combos = len(roles) * len(sites)

    for role in roles:
        for site_key in sites:
            combo_index += 1
            if _is_cancelled(sid):
                log(f"[SCRAPE] Cancelled by user", sid)
                _set_raw(sid, all_jobs)
                _save_elapsed(sid)
                update_session(sid, status="done")
                return

            module_name, func_name = SITE_MAP.get(site_key, (None, None))
            if not module_name:
                log(f"[SCRAPE] Unknown site: {site_key}", sid)
                continue

            log(f"[SCRAPE] {role} @ {site_key} ({combo_index}/{total_combos})...", sid)
            try:
                mod = importlib.import_module(f"scrapers.{module_name}")
                scraper_fn = getattr(mod, func_name)
                kwargs = {"roles": [role]}
                if site_key in ("indeed", "linkedin"):
                    kwargs["location"] = location or "United States"
                    kwargs["results_wanted"] = scrape_limit
                    kwargs["internship_mode"] = internship_mode
                    kwargs["hours_old"] = hours_old
                if site_key == "linkedin":
                    kwargs["fetch_descriptions"] = False
                if site_key == "indeed":
                    kwargs["country_indeed"] = indeed_country
                jobs = scraper_fn(**kwargs)
            except TypeError:
                try:
                    jobs = scraper_fn()
                except Exception as e:
                    log(f"[SCRAPE] {site_key} failed: {e}", sid)
                    continue
            except Exception as e:
                log(f"[SCRAPE] {site_key} failed: {e}", sid)
                continue

            # Title-filter by this role and tag matching jobs
            combo_jobs = []
            for j in jobs:
                if _role_match(j.get("title", ""), [role]) > 0:
                    j["_matched_role"] = role
                    combo_jobs.append(j)
            log(f"[SCRAPE] {role} @ {site_key}: {len(jobs)} fetched, {len(combo_jobs)} title-matched", sid)

            if not combo_jobs:
                _delay(1, 3)
                continue

            # Fetch descriptions only for title-matched jobs (LinkedIn skips them in the scraper)
            if site_key == "linkedin":
                from scrapers.linkedin_scraper import enrich_descriptions as _enrich
                _enrich(combo_jobs)

            # Experience level detection (required for internship filter and display)
            for j in combo_jobs:
                j["experience_level"] = detect_experience_level(
                    j.get("title", ""), j.get("description", "")
                )

            # In internship mode, drop non-entry-level for this combo
            if internship_mode:
                before = len(combo_jobs)
                combo_jobs = [j for j in combo_jobs if j.get("experience_level") in ("internship", "entry_level")]
                dropped = before - len(combo_jobs)
                if dropped:
                    log(f"[SCRAPE] {role} @ {site_key}: internship filter {before} → {len(combo_jobs)} (dropped {dropped})", sid)
                if not combo_jobs:
                    _delay(1, 3)
                    continue

            # In normal mode, drop entry-level jobs
            if not internship_mode:
                before = len(combo_jobs)
                combo_jobs = [j for j in combo_jobs if j.get("experience_level") not in ("entry_level",)]
                dropped = before - len(combo_jobs)
                if dropped:
                    log(f"[SCRAPE] {role} @ {site_key}: normal filter {before} → {len(combo_jobs)} (dropped {dropped} entry-level)", sid)
                if not combo_jobs:
                    _delay(1, 3)
                    continue

            # Dedup against accumulated jobs
            new_count = 0
            for j in combo_jobs:
                key = j.get("url", "") or f"{j.get('title', '')}|{j.get('company', '')}"
                if key not in seen_urls:
                    seen_urls.add(key)
                    all_jobs.append(j)
                    new_count += 1
            log(f"[SCRAPE] {role} @ {site_key}: {new_count} new after dedup", sid)

            if not all_jobs:
                _delay(1, 3)
                continue

            # Keyword-score all accumulated jobs
            for j in all_jobs:
                if "keyword_score" not in j or not isinstance(j["keyword_score"], int):
                    j["keyword_score"] = _kw_score(
                        j.get("title", ""),
                        j.get("description", ""),
                        j.get("tags", []),
                        keywords=keywords or [],
                    )
            all_jobs.sort(key=lambda j: j.get("keyword_score", 0), reverse=True)

            # Write partial results — frontend picks these up during polling
            _set_raw(sid, all_jobs)
            log(f"[SCRAPE] {role} @ {site_key}: {len(all_jobs)} total jobs stored", sid)

            # Staggered delay before next combo
            _delay(1, 3)

    log(f"[SCRAPE] Pipeline complete — {len(all_jobs)} total jobs", sid)
    _harvest_companies(all_jobs)
    update_session(sid, scraped=len(all_jobs))
    _save_elapsed(sid)
    update_session(sid, status="done")

    if not all_jobs:
        _set_raw(sid, [])
        log(f"[SCRAPE] No jobs found", sid)


def _run_scrape_guarded(sid: str, *args, **kwargs):
    """Run run_scrape so the session always ends in a terminal status."""
    try:
        run_scrape(sid, *args, **kwargs)
    except Exception as e:
        log(f"[SCRAPE] Pipeline error: {e}", sid)
    finally:
        try:
            _save_elapsed(sid)
            update_session(sid, status="done")
        except Exception:
            pass


@router.post("")
async def trigger_scrape(req: ScrapeRequest):
    if not req.search_id:
        return {"message": "Missing search_id", "status": "error"}
    sid = req.search_id
    log(f"[SCRAPE] Search triggered — sites={req.sites}, "
          f"mode={'internship' if req.internship_mode else 'normal'}", sid)
    t = threading.Thread(target=_run_scrape_guarded, args=(
        sid, req.sites, req.roles, req.location, req.indeed_country,
    ), kwargs={
        "keywords": req.keywords,
        "internship_mode": req.internship_mode,
        "user_email": req.user_email,
        "resume_filename": req.resume_filename,
        "scrape_limit": req.scrape_limit,
        "hours_old": req.hours_old,
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

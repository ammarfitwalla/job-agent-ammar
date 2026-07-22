import os
import threading
import tempfile
from typing import Optional
from datetime import datetime, timedelta
from fastapi import APIRouter, Query
from api.schemas import ScrapeRequest
from utils.logger import log
from db import create_session, update_session, get_session, set_filtered_jobs, add_filtered_job, count_filtered_jobs, get_events

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


def _run_scrape(req: ScrapeRequest):
    run_scrape(req.search_id, req.sites, req.keywords, req.resume_text, req.roles,
               req.adzuna_country, req.location, req.indeed_country,
               req.internship_mode, req.min_relevant, req.max_passes,
               original_resume=req.original_resume, user_email=req.user_email)


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

_TECH_KEYWORDS = {
    "python", "docker", "kubernetes", "aws", "azure", "gcp", "linux",
    "jenkins", "terraform", "ansible", "git", "mysql", "postgresql",
    "mongodb", "redis", "nginx", "react", "angular", "vue", "node",
    "typescript", "javascript", "java", "golang", "rust", "swift",
    "kotlin", "scala", "tensorflow", "pytorch", "scikit", "pandas",
    "numpy", "hadoop", "spark", "kafka", "elasticsearch", "grafana",
    "prometheus", "tableau", "powerbi", "salesforce", "hubspot",
    "autocad", "revit", "solidworks", "matlab", "photoshop",
    "illustrator", "premiere", "aftereffects", "westlaw", "lexisnexis",
    "epic", "ehr", "emr", "crm", "quickbooks", "sap", "oracle",
}


def _score_jobs(jobs: list, keywords: list[str], resume_text: str,
                sid: str = None, internship_mode: bool = False,
                roles: Optional[list] = None,
                user_email: str = "") -> list:
    from match_engine.relevance_engine import filter_jobs
    from db import get_company_user_counts, get_user

    def on_scored(job):
        if sid:
            add_filtered_job(sid, job)

    companies = list({j.get("company", "") for j in jobs if j.get("company")})
    company_counts = get_company_user_counts(companies, exclude_email=user_email or None)
    user_data = get_user(user_email) if user_email else None
    user_company = user_data.get("company", "").lower() if user_data else ""
    if user_company and user_company in company_counts:
        company_counts[user_company] = 0

    if internship_mode:
        min_threshold = 35
    else:
        min_threshold = 0
    kw = dict(llm_weight=0.85, kw_weight=0.15) if internship_mode else {}
    relevant = filter_jobs(jobs, min_score=min_threshold, keywords=keywords, resume=resume_text,
                           roles=roles,
                           progress_callback=on_scored if sid else None,
                           internship_mode=internship_mode, sid=sid, **kw,
                           cancel_check=lambda: _is_cancelled(sid),
                           company_user_counts=company_counts)
    log(f"[SCORE] {len(relevant)} relevant out of {len(jobs)}", sid)
    return relevant


def _is_cancelled(sid: str) -> bool:
    s = get_session(sid)
    return bool(s and s.get("cancel"))


_RESUMES_UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "resumes")

def _resumes_dir():
    return os.path.join(tempfile.gettempdir(), "job_agent_resumes")

def run_scrape(sid: str, sites: list[str], keywords: list[str], resume_text: str,
               roles=None, adzuna_country="us", location="", indeed_country="USA",
               internship_mode=False, min_relevant=5, max_passes=3,
               original_resume="", user_email=""):
    if not sid:
        log(f"[SCRAPE] No search_id provided, aborting", sid)
        return

    create_session(sid, sites=sites, keywords=keywords, roles=roles or [],
                   keywords_count=len(keywords), roles_count=len(roles or []),
                   resume_length=len(resume_text), internship_mode=internship_mode,
                   location=location)

    if original_resume:
        src = os.path.join(_RESUMES_UPLOAD_DIR, original_resume)
        ext = os.path.splitext(original_resume)[1]
        dst = os.path.join(_RESUMES_UPLOAD_DIR, f"{sid}{ext}")
        try:
            os.rename(src, dst)
        except OSError:
            try:
                import shutil
                shutil.copy2(src, dst)
                os.remove(src)
            except Exception:
                pass

    d = _resumes_dir()
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"{sid}.txt"), "w", encoding="utf-8") as f:
        f.write(resume_text)
    update_session(sid, status="running", cancel=False, pass_num=0,
                   max_passes=max_passes, filtered_gen=0, queue_position=0, scraped=0)

    log(f"[SCRAPE] Starting scrape for sites: {sites}", sid)
    log(f"[SCRAPE] Selected keywords: {keywords}", sid)
    if roles:
        log(f"[SCRAPE] Selected roles: {len(roles)} — {roles[:5]}...", sid)
    log(f"[SCRAPE] Internship mode: {internship_mode}, min_relevant={min_relevant}", sid)

    try:
        if internship_mode:
            _scrape_internship(sid, sites, keywords, resume_text, roles,
                               adzuna_country, location, indeed_country,
                               min_relevant, max_passes, user_email=user_email)
        else:
            _scrape_normal(sid, sites, keywords, resume_text, roles,
                           adzuna_country, location, indeed_country,
                           user_email=user_email)
    except Exception as e:
        log(f"[SCRAPE] Pipeline error: {e}", sid)
        import traceback
        traceback.print_exc()
        update_session(sid, status="error")


def _scrape_normal(sid, sites, keywords, resume_text, roles,
                   adzuna_country, location, indeed_country,
                   user_email=""):
    import importlib

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
                if site_key in ("indeed", "linkedin"):
                    kwargs["location"] = location or "United States"
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
        log(f"[SCRAPE] No jobs found, skipping relevance engine", sid)
        set_filtered_jobs(sid, [])
        _save_elapsed(sid)
        update_session(sid, status="done")
        return

    relevant = _score_jobs(all_jobs, keywords, resume_text, sid=sid, internship_mode=False, roles=roles, user_email=user_email)
    set_filtered_jobs(sid, relevant)
    _save_elapsed(sid)
    update_session(sid, status="done", filtered_gen=1)
    log(f"[SCRAPE] Pipeline complete — {len(all_jobs)} raw → {len(relevant)} relevant", sid)


def _scrape_internship(sid, sites, keywords, resume_text, roles,
                       adzuna_country, location, indeed_country,
                       min_relevant, max_passes,
                       user_email=""):
    import importlib
    from utils.experience_level import detect_experience_level
    from match_engine.relevance_engine import filter_jobs
    from db import get_company_user_counts, get_user

    seen_urls = set()
    all_jobs = []
    scored_ids = set()
    all_relevant = []
    pass_num = 0
    did_write = False

    while pass_num < max_passes:
        pass_num += 1
        update_session(sid, pass_num=pass_num)

        s = get_session(sid)
        if s and s.get("cancel"):
            log(f"[SCRAPE] Cancelled by user", sid)
            update_session(sid, status="done")
            return

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
                log(f"[SCRAPE] Pass {pass_num}/{max_passes} — {site_key}...", sid)
                mod = importlib.import_module(f"scrapers.{module_name}")
                scraper_fn = getattr(mod, func_name)
                try:
                    kwargs = {"roles": roles}
                    if site_key == "adzuna":
                        kwargs["country"] = adzuna_country
                    if site_key in ("indeed", "linkedin"):
                        kwargs["location"] = location or "United States"
                        kwargs["results_wanted"] = 20 * pass_num
                        kwargs["hours_old"] = 72 * pass_num
                    if site_key == "indeed":
                        kwargs["country_indeed"] = indeed_country
                    kwargs["internship_mode"] = True
                    jobs = scraper_fn(**kwargs)
                except TypeError:
                    try:
                        jobs = scraper_fn(roles=roles)
                    except TypeError:
                        jobs = scraper_fn()

                new_count = 0
                for j in jobs:
                    uid = j.get("url", "") or f"{j.get('title', '')}|{j.get('company', '')}"
                    if uid and uid not in seen_urls:
                        seen_urls.add(uid)
                        all_jobs.append(j)
                        new_count += 1
                    elif not uid:
                        all_jobs.append(j)
                        new_count += 1

                log(f"[SCRAPE] {site_key}: {len(jobs)} fetched, {new_count} new (total {len(all_jobs)})", sid)
                from utils.delay import delay as _rd
                _rd(3, 6)
            except Exception as e:
                log(f"[SCRAPE] {site_key} failed: {e}", sid)

        update_session(sid, scraped=len(all_jobs))

        for job in all_jobs:
            if "experience_level" not in job:
                job["experience_level"] = detect_experience_level(
                    job.get("title", ""), job.get("description", ""))

        candidates = [j for j in all_jobs
                      if j.get("experience_level") in ("internship", "entry_level")]
        new_candidates = [j for j in candidates if id(j) not in scored_ids]
        for j in new_candidates:
            scored_ids.add(id(j))

        if new_candidates:
            log(f"[SCRAPE] Pass {pass_num}: {len(new_candidates)} new candidates "
                  f"to score (total {len(all_relevant)} relevant so far)", sid)
            companies = list({j.get("company", "") for j in new_candidates if j.get("company")})
            company_counts = get_company_user_counts(companies, exclude_email=user_email or None)
            user_data = get_user(user_email) if user_email else None
            user_company = user_data.get("company", "").lower() if user_data else ""
            if user_company and user_company in company_counts:
                company_counts[user_company] = 0
            min_threshold = 35
            batch = filter_jobs(new_candidates, min_score=min_threshold,
                                keywords=keywords, resume=resume_text,
                                roles=roles,
                                progress_callback=lambda j: add_filtered_job(sid, j),
                                internship_mode=True, sid=sid,
                                llm_weight=0.85, kw_weight=0.15,
                                cancel_check=lambda: _is_cancelled(sid),
                                company_user_counts=company_counts)

            if batch:
                all_relevant.extend(batch)
                all_relevant.sort(key=lambda j: j.get("total_score", 0), reverse=True)
                set_filtered_jobs(sid, all_relevant)
                s = get_session(sid)
                update_session(sid, filtered_gen=(s.get("filtered_gen", 0) if s else 0) + 1)
                did_write = True

        log(f"[SCRAPE] Pass {pass_num}: {len(all_jobs)} raw, "
              f"{len(candidates)} exp-filtered, {len(all_relevant)} relevant", sid)
        if len(all_relevant) >= min_relevant:
            log(f"[SCRAPE] Enough relevant ({len(all_relevant)} >= {min_relevant}), stopping", sid)
            break

    _harvest_companies(all_jobs)

    s = get_session(sid)
    if not did_write:
        set_filtered_jobs(sid, all_relevant)
        s = get_session(sid)
        update_session(sid, filtered_gen=(s.get("filtered_gen", 0) if s else 0) + 1)
    _save_elapsed(sid)
    update_session(sid, status="done")
    log(f"[SCRAPE] Pipeline complete — {len(all_jobs)} raw → {len(all_relevant)} relevant", sid)


@router.post("")
async def trigger_scrape(req: ScrapeRequest):
    if not req.search_id:
        return {"message": "Missing search_id", "status": "error"}
    sid = req.search_id
    log(f"[SCRAPE] Search triggered — sites={req.sites}, "
          f"mode={'internship' if req.internship_mode else 'normal'}", sid)
    t = threading.Thread(target=_run_scrape, args=(req,), daemon=True)
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
        return {"status": "idle", "last_scrape_raw": 0, "last_scrape_relevant": 0,
                "pass_num": 0, "max_passes": 0, "filtered_gen": 0, "queue_position": 0}
    s = get_session(search_id)
    if s is None:
        return {"status": "idle", "last_scrape_raw": 0, "last_scrape_relevant": 0,
                "pass_num": 0, "max_passes": 0, "filtered_gen": 0, "queue_position": 0}
    return {
        "status": s.get("status", "idle"),
        "last_scrape_raw": s.get("scraped") or 0,
        "last_scrape_relevant": count_filtered_jobs(search_id),
        "pass_num": s.get("pass_num", 0),
        "max_passes": s.get("max_passes", 0),
        "filtered_gen": s.get("filtered_gen", 0),
        "queue_position": s.get("queue_position", 0),
        "elapsed": s.get("elapsed_seconds", 0),
        "logs": get_events(search_id, limit=50),
    }

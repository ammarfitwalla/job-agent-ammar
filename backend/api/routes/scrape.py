from datetime import datetime
from fastapi import APIRouter, BackgroundTasks, Query
from api.schemas import ScrapeRequest
from utils.logger import log
import threading
from collections import deque
from db import create_session, update_session, get_session, set_filtered_jobs, add_filtered_job, count_filtered_jobs, get_events

router = APIRouter(prefix="/scrape", tags=["scrape"])

_scrape_lock = threading.Lock()


def _save_elapsed(sid):
    s = get_session(sid)
    if s and s.get("created_at"):
        elapsed = (datetime.utcnow() - datetime.fromisoformat(s["created_at"])).total_seconds()
        update_session(sid, elapsed_seconds=round(elapsed, 1))

_scrape_queue: deque[ScrapeRequest] = deque()


def _process_queue():
    if _scrape_queue:
        next_req = _scrape_queue.popleft()
        sid = next_req.search_id
        if sid:
            update_session(sid, queue_position=len(_scrape_queue))
        print(f"[SCRAPE] Starting next queued scrape ({len(_scrape_queue)} remaining in queue)")
        t = threading.Thread(target=_run_scrape_wrapper, args=(next_req,), daemon=True)
        t.start()
    else:
        _scrape_lock.release()


def _run_scrape_wrapper(req: ScrapeRequest):
    try:
        run_scrape(req.search_id, req.sites, req.keywords, req.resume_text, req.roles,
                   req.adzuna_country, req.location, req.indeed_country,
                   req.internship_mode, req.min_relevant, req.max_passes)
    finally:
        _process_queue()


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
                sid: str = None, internship_mode: bool = False) -> list:
    from match_engine.relevance_engine import filter_jobs

    def on_scored(job):
        if sid:
            add_filtered_job(sid, job)

    if internship_mode:
        has_tech = any(kw.lower() in _TECH_KEYWORDS for kw in keywords)
        min_threshold = 30 if not has_tech else 50
    else:
        min_threshold = 0
    relevant = filter_jobs(jobs, min_score=min_threshold, keywords=keywords, resume=resume_text,
                           progress_callback=on_scored if sid else None,
                           internship_mode=internship_mode, sid=sid)
    log(f"[SCORE] {len(relevant)} relevant out of {len(jobs)}", sid)
    return relevant


def run_scrape(sid: str, sites: list[str], keywords: list[str], resume_text: str,
               roles=None, adzuna_country="us", location="", indeed_country="USA",
               internship_mode=False, min_relevant=5, max_passes=3):
    if not sid:
        log(f"[SCRAPE] No search_id provided, aborting", sid)
        return

    create_session(sid, sites=sites, keywords_count=len(keywords),
                   roles_count=len(roles or []), resume_length=len(resume_text),
                   internship_mode=internship_mode)
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
                               min_relevant, max_passes)
        else:
            _scrape_normal(sid, sites, keywords, resume_text, roles,
                           adzuna_country, location, indeed_country)
    except Exception as e:
        log(f"[SCRAPE] Pipeline error: {e}", sid)
        import traceback
        traceback.print_exc()
        update_session(sid, status="error")


def _scrape_normal(sid, sites, keywords, resume_text, roles,
                   adzuna_country, location, indeed_country):
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
            from utils.rate_limiter import delay as _rd
            _rd(3, 6)
        except Exception as e:
            log(f"[SCRAPE] {site_key} failed: {e}", sid)

    log(f"[SCRAPE] Total raw jobs: {len(all_jobs)}", sid)
    update_session(sid, scraped=1)

    if not all_jobs:
        log(f"[SCRAPE] No jobs found, skipping relevance engine", sid)
        set_filtered_jobs(sid, [])
        _save_elapsed(sid)
        update_session(sid, status="done")
        return

    relevant = _score_jobs(all_jobs, keywords, resume_text, sid=sid, internship_mode=False)
    set_filtered_jobs(sid, relevant)
    _save_elapsed(sid)
    update_session(sid, status="done", filtered_gen=1)
    log(f"[SCRAPE] Pipeline complete — {len(all_jobs)} raw → {len(relevant)} relevant", sid)


def _scrape_internship(sid, sites, keywords, resume_text, roles,
                       adzuna_country, location, indeed_country,
                       min_relevant, max_passes):
    import importlib
    from utils.experience_level import detect_experience_level
    from match_engine.relevance_engine import filter_jobs

    seen_urls = set()
    all_jobs = []
    scored_ids = set()
    all_relevant = []
    pass_num = 0

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
                from utils.rate_limiter import delay as _rd
                _rd(3, 6)
            except Exception as e:
                log(f"[SCRAPE] {site_key} failed: {e}", sid)

        update_session(sid, scraped=1)

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
            has_tech = any(kw.lower() in _TECH_KEYWORDS for kw in keywords)
            min_threshold = 30 if not has_tech else 50
            batch = filter_jobs(new_candidates, min_score=min_threshold,
                                keywords=keywords, resume=resume_text,
                                progress_callback=lambda j: add_filtered_job(sid, j),
                                internship_mode=True, sid=sid)

            if batch:
                all_relevant.extend(batch)
                all_relevant.sort(key=lambda j: j.get("total_score", 0), reverse=True)
                set_filtered_jobs(sid, all_relevant)
                s = get_session(sid)
                update_session(sid, filtered_gen=(s.get("filtered_gen", 0) if s else 0) + 1)

        log(f"[SCRAPE] Pass {pass_num}: {len(all_jobs)} raw, "
              f"{len(candidates)} exp-filtered, {len(all_relevant)} relevant", sid)
        if len(all_relevant) >= min_relevant:
            log(f"[SCRAPE] Enough relevant ({len(all_relevant)} >= {min_relevant}), stopping", sid)
            break

    set_filtered_jobs(sid, all_relevant)
    s = get_session(sid)
    _save_elapsed(sid)
    update_session(sid, filtered_gen=(s.get("filtered_gen", 0) if s else 0) + 1,
                   status="done")
    log(f"[SCRAPE] Pipeline complete — {len(all_jobs)} raw → {len(all_relevant)} relevant", sid)


@router.post("")
async def trigger_scrape(background_tasks: BackgroundTasks, req: ScrapeRequest):
    if not req.search_id:
        return {"message": "Missing search_id", "status": "error"}
    sid = req.search_id
    log(f"[SCRAPE] Search triggered — sites={req.sites}, "
          f"mode={'internship' if req.internship_mode else 'normal'}", sid)
    if _scrape_lock.acquire(blocking=False):
        if sid:
            update_session(sid, queue_position=0)
        background_tasks.add_task(_run_scrape_wrapper, req)
        return {"message": "Scrape started", "status": "running"}
    else:
        _scrape_queue.append(req)
        pos = len(_scrape_queue)
        if sid:
            update_session(sid, queue_position=pos)
        log(f"[SCRAPE] Queued at position {pos}", sid)
        return {"message": f"Another scrape in progress — queued at position {pos}",
                "status": "queued", "queue_position": pos}


@router.post("/stop")
async def stop_scrape(search_id: str = Query("")):
    if not search_id:
        return {"message": "Missing search_id", "status": "error"}
    log(f"[STOP] Stop requested for session {search_id}", search_id)
    update_session(search_id, cancel=True, status="done")
    _scrape_queue.clear()
    log(f"[STOP] Cleared queue")
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
        "last_scrape_raw": 1 if s.get("scraped") else 0,
        "last_scrape_relevant": count_filtered_jobs(search_id),
        "pass_num": s.get("pass_num", 0),
        "max_passes": s.get("max_passes", 0),
        "filtered_gen": s.get("filtered_gen", 0),
        "queue_position": s.get("queue_position", 0),
        "elapsed": s.get("elapsed_seconds", 0),
        "logs": get_events(search_id, limit=50),
    }

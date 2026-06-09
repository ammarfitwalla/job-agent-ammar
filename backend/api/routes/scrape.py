from fastapi import APIRouter, BackgroundTasks
from api.schemas import ScrapeRequest, ScrapeResponse
from utils.logger import log

router = APIRouter(prefix="/scrape", tags=["scrape"])

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


def _score_jobs(jobs: list, keywords: list[str], resume_text: str, job_store: dict = None, internship_mode: bool = False) -> list:
    from match_engine.relevance_engine import filter_jobs

    def on_scored(job):
        if job_store is not None:
            job_store["filtered"].append(job)

    if internship_mode:
        has_tech = any(kw.lower() in _TECH_KEYWORDS for kw in keywords)
        min_threshold = 30 if not has_tech else 50
    else:
        min_threshold = 0
    relevant = filter_jobs(jobs, min_score=min_threshold, keywords=keywords, resume=resume_text, progress_callback=on_scored if job_store else None, internship_mode=internship_mode)
    log(f"[SCORE] {len(relevant)} relevant out of {len(jobs)}")
    return relevant


def run_scrape(sites: list[str], keywords: list[str], resume_text: str, roles=None, adzuna_country="us", location="", indeed_country="USA", internship_mode=False, min_relevant=5, max_passes=3):
    import sys
    sys.path.insert(0, ".")
    from api.main import job_store
    import importlib

    print(f"[SCRAPE] Starting scrape for sites: {sites}")
    print(f"[SCRAPE] Selected keywords: {keywords}")
    if roles:
        print(f"[SCRAPE] Selected roles: {len(roles)} — {roles[:5]}...")
    print(f"[SCRAPE] Internship mode: {internship_mode}, min_relevant={min_relevant}")
    job_store["internship_mode"] = internship_mode
    job_store["scrape_status"] = "running"
    job_store["cancel"] = False
    job_store["raw"] = []
    job_store["filtered"] = []
    job_store["pass_num"] = 0
    job_store["max_passes"] = max_passes
    job_store["filtered_gen"] = 0

    try:
        if internship_mode:
            _scrape_internship(sites, keywords, resume_text, roles, adzuna_country, location, indeed_country, min_relevant, max_passes)
        else:
            _scrape_normal(sites, keywords, resume_text, roles, adzuna_country, location, indeed_country)
    except Exception as e:
        print(f"[SCRAPE] Pipeline error: {e}")
        import traceback
        traceback.print_exc()
        job_store["scrape_status"] = "error"


def _scrape_normal(sites, keywords, resume_text, roles, adzuna_country, location, indeed_country):
    from api.main import job_store
    import importlib

    all_jobs = []

    for site_key in sites:
        if job_store.get("cancel"):
            print(f"[SCRAPE] Cancelled by user")
            job_store["scrape_status"] = "done"
            return

        module_name, func_name = SITE_MAP.get(site_key, (None, None))
        if not module_name:
            print(f"[SCRAPE] Unknown site: {site_key}")
            continue
        try:
            print(f"[SCRAPE] Running {site_key}...")
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
            print(f"[SCRAPE] {site_key} returned {len(jobs)} jobs")
            all_jobs.extend(jobs)
            from utils.rate_limiter import delay as _rd
            _rd(3, 6)
        except Exception as e:
            print(f"[SCRAPE] {site_key} failed: {e}")

    print(f"[SCRAPE] Total raw jobs: {len(all_jobs)}")
    job_store["raw"] = all_jobs

    if not all_jobs:
        print(f"[SCRAPE] No jobs found, skipping relevance engine")
        job_store["filtered"] = []
        job_store["scrape_status"] = "done"
        return

    relevant = _score_jobs(all_jobs, keywords, resume_text, job_store, internship_mode=False)
    job_store["filtered"] = relevant
    job_store["scrape_status"] = "done"
    print(f"[SCRAPE] Pipeline complete — {len(all_jobs)} raw → {len(relevant)} relevant")


def _scrape_internship(sites, keywords, resume_text, roles, adzuna_country, location, indeed_country, min_relevant, max_passes):
    from api.main import job_store
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
        job_store["pass_num"] = pass_num

        if job_store.get("cancel"):
            print(f"[SCRAPE] Cancelled by user")
            job_store["scrape_status"] = "done"
            return

        for site_key in sites:
            if job_store.get("cancel"):
                print(f"[SCRAPE] Cancelled by user")
                job_store["scrape_status"] = "done"
                return

            module_name, func_name = SITE_MAP.get(site_key, (None, None))
            if not module_name:
                print(f"[SCRAPE] Unknown site: {site_key}")
                continue
            try:
                print(f"[SCRAPE] Pass {pass_num}/{max_passes} — {site_key}...")
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

                print(f"[SCRAPE] {site_key}: {len(jobs)} fetched, {new_count} new (total {len(all_jobs)})")
                from utils.rate_limiter import delay as _rd
                _rd(3, 6)
            except Exception as e:
                print(f"[SCRAPE] {site_key} failed: {e}")

        job_store["raw"] = list(all_jobs)

        # Experience filter + score new candidates
        for job in all_jobs:
            if "experience_level" not in job:
                job["experience_level"] = detect_experience_level(job.get("title", ""), job.get("description", ""))

        candidates = [j for j in all_jobs if j.get("experience_level") in ("internship", "entry_level")]
        new_candidates = [j for j in candidates if id(j) not in scored_ids]
        for j in new_candidates:
            scored_ids.add(id(j))

        if new_candidates:
            print(f"[SCRAPE] Pass {pass_num}: {len(new_candidates)} new candidates to score (total {len(all_relevant)} relevant so far)")
            has_tech = any(kw.lower() in _TECH_KEYWORDS for kw in keywords)
            min_threshold = 30 if not has_tech else 50
            batch = filter_jobs(new_candidates, min_score=min_threshold, keywords=keywords, resume=resume_text,
                                progress_callback=lambda j: job_store.setdefault("filtered", []).append(j),
                                internship_mode=True)

            all_relevant.extend(batch)
            all_relevant.sort(key=lambda j: j.get("total_score", 0), reverse=True)
            job_store["filtered"] = list(all_relevant)
            job_store["filtered_gen"] += 1

        print(f"[SCRAPE] Pass {pass_num}: {len(all_jobs)} raw, {len(candidates)} experience-filtered, {len(all_relevant)} relevant")
        if len(all_relevant) >= min_relevant:
            print(f"[SCRAPE] Enough relevant ({len(all_relevant)} >= {min_relevant}), stopping")
            break

    job_store["raw"] = all_jobs
    job_store["filtered"] = list(all_relevant)
    job_store["filtered_gen"] += 1
    job_store["scrape_status"] = "done"
    print(f"[SCRAPE] Pipeline complete — {len(all_jobs)} raw → {len(all_relevant)} relevant")


@router.post("")
async def trigger_scrape(background_tasks: BackgroundTasks, req: ScrapeRequest):
    print(f"[TRIGGER] Search Jobs clicked — sites={req.sites}, keywords count={len(req.keywords)}")
    print(f"[TRIGGER] Adding background task...")
    background_tasks.add_task(run_scrape, req.sites, req.keywords, req.resume_text, req.roles, req.adzuna_country, req.location, req.indeed_country, req.internship_mode, req.min_relevant, req.max_passes)
    print(f"[TRIGGER] Background task added, returning immediately")
    return {"message": "Scrape started in background", "status": "running"}


@router.post("/stop")
async def stop_scrape():
    from api.main import job_store
    print(f"[STOP] Stop requested by user")
    job_store["cancel"] = True
    job_store["scrape_status"] = "done"
    print(f"[STOP] Cancel flag set, status set to done")
    return {"message": "Scrape cancelled", "status": "done"}


@router.post("/reprocess")
async def reprocess_jobs(req: ScrapeRequest):
    from api.main import job_store
    print(f"[REPROCESS] Re-scoring {len(job_store.get('raw', []))} raw jobs with keywords={req.keywords}")
    job_store["scrape_status"] = "running"

    raw = job_store.get("raw", [])
    if not raw:
        print(f"[REPROCESS] No raw jobs to reprocess")
        job_store["scrape_status"] = "done"
        return {"message": "No raw jobs to reprocess", "status": "done", "total": 0}

    if req.internship_mode:
        raw = [j for j in raw if j.get("experience_level") in ("internship", "entry_level")]
        print(f"[REPROCESS] Internship filter: {len(raw)} jobs remaining")

    relevant = _score_jobs(raw, req.keywords, req.resume_text, internship_mode=req.internship_mode)
    job_store["filtered"] = relevant
    job_store["scrape_status"] = "done"
    print(f"[REPROCESS] Done — {len(relevant)} relevant")
    return {"message": "Reprocessed", "status": "done", "total": len(relevant)}


@router.get("/status")
async def scrape_status():
    from api.main import job_store
    status = job_store.get("scrape_status", "idle")
    raw_count = len(job_store.get("raw", []))
    filtered_count = len(job_store.get("filtered", []))
    pass_num = job_store.get("pass_num", 0)
    max_passes = job_store.get("max_passes", 0)
    filtered_gen = job_store.get("filtered_gen", 0)
    print(f"[STATUS] Polled — status={status}, raw={raw_count}, filtered={filtered_count}, pass={pass_num}/{max_passes}")
    return {
        "status": status,
        "last_scrape_raw": raw_count,
        "last_scrape_relevant": filtered_count,
        "pass_num": pass_num,
        "max_passes": max_passes,
        "filtered_gen": filtered_gen,
    }

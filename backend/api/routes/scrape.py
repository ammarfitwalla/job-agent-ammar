from fastapi import APIRouter, BackgroundTasks
from api.schemas import ScrapeRequest, ScrapeResponse

router = APIRouter(prefix="/scrape", tags=["scrape"])

SITE_MAP = {
    "remoteok": ("remoteok_scraper", "scrape_remoteok"),
    "weworkremotely": ("weworkremotely_scraper", "scrape_wwr"),
    "naukri": ("naukri_scraper", "scrape_naukri"),
    "gulftalent": ("gulftalent_scraper", "scrape_gulftalent"),
    "eurojobs": ("eurojobs_scraper", "scrape_eurojobs"),
}


def _score_jobs(jobs: list, keywords: list[str], resume_text: str) -> list:
    """Run relevance engine on a list of jobs with given keywords/resume."""
    from match_engine.relevance_engine import filter_jobs

    if resume_text:
        import config as cfg
        cfg.RESUME_PATH = resume_text
        from match_engine import resume_data
        resume_data.RESUME_TEXT = resume_text

    relevant = filter_jobs(jobs, keywords=keywords)
    print(f"[SCORE] {len(relevant)} relevant out of {len(jobs)}")
    return relevant


def run_scrape(sites: list[str], keywords: list[str], resume_text: str, roles=None):
    import sys
    sys.path.insert(0, ".")
    from api.main import job_store
    import importlib

    print(f"[SCRAPE] Starting scrape for sites: {sites}")
    print(f"[SCRAPE] Selected keywords: {keywords}")
    if roles:
        print(f"[SCRAPE] Selected roles: {len(roles)} — {roles[:5]}...")
    job_store["scrape_status"] = "running"
    job_store["cancel"] = False
    job_store["filtered"] = []
    all_jobs = []

    try:
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
                        jobs = scraper_fn(roles=roles)
                    except TypeError:
                        jobs = scraper_fn()
                    print(f"[SCRAPE] {site_key} returned {len(jobs)} jobs")
                    all_jobs.extend(jobs)
                    # Rate limit between sites
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

        # Filter by user's keywords — only keep jobs matching at least one
        if keywords:
            kw_lower = [k.lower() for k in keywords]
            before = len(all_jobs)
            all_jobs = [
                j for j in all_jobs
                if any(kw in f"{j['title']} {j['description']}".lower() for kw in kw_lower)
            ]
            print(f"[SCRAPE] Keyword filter: {before} → {len(all_jobs)} jobs (dropped {before - len(all_jobs)})")

        relevant = _score_jobs(all_jobs, keywords, resume_text)
        job_store["filtered"] = relevant
        job_store["scrape_status"] = "done"
        print(f"[SCRAPE] Pipeline complete — {len(all_jobs)} raw → {len(relevant)} relevant")
    except Exception as e:
        print(f"[SCRAPE] Pipeline error: {e}")
        job_store["scrape_status"] = "error"


@router.post("")
async def trigger_scrape(background_tasks: BackgroundTasks, req: ScrapeRequest):
    print(f"[TRIGGER] Search Jobs clicked — sites={req.sites}, keywords count={len(req.keywords)}")
    print(f"[TRIGGER] Adding background task...")
    background_tasks.add_task(run_scrape, req.sites, req.keywords, req.resume_text, req.roles)
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

    relevant = _score_jobs(raw, req.keywords, req.resume_text)
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
    print(f"[STATUS] Polled — status={status}, raw={raw_count}, filtered={filtered_count}")
    return {
        "status": status,
        "last_scrape_raw": raw_count,
        "last_scrape_relevant": filtered_count,
    }

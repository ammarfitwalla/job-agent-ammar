"""End-to-end scheduler flow test.

Runs a full prewarm pass against a throwaway SQLite DB using fake scrapers and
verifies that jobs actually flow into job_cache, that the prewarm_queue / leader
lock behave, and that pass 2 is a no-op (everything fresh).

Run (from anywhere):

    D:\Python\Python310\python.exe backend\scripts\test_scheduler_flow.py

Exits 0 when every check passes, 1 otherwise. Uses a temp DB — the real
job_agent.db is never touched.
"""
import json
import os
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import db
import config
import scheduler
import scrapers.indeed_scraper
import scrapers.linkedin_scraper
import scrapers.naukri_scraper

EXPECTED_STATES = ["Karnataka", "Maharashtra"]


def _fake_scraper(site):
    """Deterministic scraper: yields 8 title-matching jobs per combo."""
    def fake(**kwargs):
        role = kwargs["roles"][0]
        internship = bool(kwargs.get("internship_mode"))
        results_wanted = int(kwargs.get("results_wanted") or 30)
        location = kwargs.get("location") or EXPECTED_STATES[0]
        n = min(results_wanted, 8)

        if internship:
            title = f"{role} Intern"
            job_level = "internship"
            description = "Internship program. Training provided and mentorship included."
        else:
            title = f"{role} Senior"
            job_level = ""
            description = "Owns feature delivery end to end. Requires 5+ years of experience."

        def gen():
            yield [
                {
                    "id": f"{site}-{i}",
                    "title": title,
                    "company": f"Fake {site.title()} Corp {i}",
                    "location": location,
                    "url": f"https://{site}.example.com/jobs/{role.replace(' ', '-')}-{i}",
                    "description": description,
                    "job_level": job_level,
                    "date_posted": "2026-08-10",
                    "source": site,
                }
                for i in range(n)
            ]

        return gen()

    return fake


def _patch_scrapers():
    import api.routes.scrape as scrape_mod
    scrapers.indeed_scraper.scrape_indeed = _fake_scraper("indeed")
    scrapers.linkedin_scraper.scrape_linkedin = _fake_scraper("linkedin")
    scrapers.naukri_scraper.scrape_naukri = _fake_scraper("naukri")
    scrapers.linkedin_scraper.enrich_descriptions = lambda jobs: None
    # City looping is covered by test_city_loop.py; keep this flow test
    # at one scrape per combo.
    scrape_mod._state_cities = lambda state, country="": []


def _tiny_config():
    config.CACHE_COUNTRIES = ["in"]
    config.CACHE_ROLES = ["Software Engineer", "Full Stack Developer"]
    config.CACHE_INCLUDE_ALL_STATES = False
    config.CACHE_STATES_OVERRIDE = {"in": list(EXPECTED_STATES)}
    config.CACHE_STATES_EXCLUDE = []
    config.CACHE_SITES_INDIA = ["indeed", "linkedin", "naukri"]
    config.CACHE_HOURS_OLD = 72
    config.CACHE_MIN_VOLUME = 1
    config.CACHE_TTL_HOURS = 12.0
    config.CACHE_PREWARM_LIMIT = 8
    config.PREWARM_WORKERS = 4
    config.PREWARM_DELAY_SECONDS = 0.0
    config.PREWARM_MAX_COMBOS_PER_RUN = 500
    config.SCHEDULER_ENABLED = True


def main() -> int:
    results = []

    def check(name, cond, detail=""):
        results.append((name, bool(cond), detail))
        print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))

    tmpdir = tempfile.mkdtemp(prefix="prewarm_flow_")
    db._DB_PATH = os.path.join(tmpdir, "test.db")

    _tiny_config()
    _patch_scrapers()
    db.init_db()

    expected = len(config.CACHE_ROLES) * len(EXPECTED_STATES) * len(config.CACHE_SITES_INDIA) * 2
    expected_jobs = expected * 8

    print(f"== grid: {len(config.CACHE_ROLES)} roles x {len(EXPECTED_STATES)} states "
          f"x {len(config.CACHE_SITES_INDIA)} sites x 2 modes = {expected} combos")

    # -- grid --------------------------------------------------------------
    grid = scheduler._grid_combos()
    check("grid has expected combo count", len(grid) == expected, f"built={len(grid)}")

    # -- pass 1 ------------------------------------------------------------
    warmed = scheduler.run_prewarm()
    check("pass 1 warmed every combo", warmed == expected, f"warmed={warmed}")

    # -- jobs flowing into job_cache --------------------------------------
    with db._get_conn() as (conn, cur):
        rows = cur.execute(
            "SELECT role, site, state, country, internship_mode, hours_old, "
            "job_count, jobs_json, scraped_at FROM job_cache"
        ).fetchall()
    check("job_cache has one row per combo", len(rows) == expected, f"rows={len(rows)}")

    total_stored = sum(r["job_count"] for r in rows)
    check("all jobs stored in cache", total_stored == expected_jobs,
          f"{total_stored}/{expected_jobs} jobs")

    missing_keys = 0
    for r in rows:
        if r["role"] not in config.CACHE_ROLES or r["site"] not in config.CACHE_SITES_INDIA:
            missing_keys += 1
        if r["state"] not in EXPECTED_STATES or r["country"] != "in" or r["hours_old"] != 72:
            missing_keys += 1
        if r["internship_mode"] not in (0, 1):
            missing_keys += 1
        if not r["scraped_at"]:
            missing_keys += 1
    check("cache keys carry role/site/state/country/mode/hours", missing_keys == 0,
          f"{missing_keys} bad rows")

    sample_jobs = json.loads(rows[0]["jobs_json"]) if rows else []
    bad_payload = 0
    for j in sample_jobs:
        if not (j.get("url") and j.get("description") and j.get("job_board") and j.get("title")):
            bad_payload += 1
    check("cached jobs keep url/description/job_board/title", bad_payload == 0,
          f"{bad_payload} incomplete jobs")

    intern_rows = [r for r in rows if r["internship_mode"] == 1]
    normal_rows = [r for r in rows if r["internship_mode"] == 0]
    intern_titles = json.loads(intern_rows[0]["jobs_json"])[0]["title"] if intern_rows else ""
    normal_titles = json.loads(normal_rows[0]["jobs_json"])[0]["title"] if normal_rows else ""
    check("internship combos hold internship jobs",
          "Intern" in intern_titles, intern_titles)
    check("normal combos hold senior jobs",
          "Senior" in normal_titles, normal_titles)

    # -- queue -------------------------------------------------------------
    queue = db.get_prewarm_queue()
    check("prewarm_queue has all combos", len(queue) == expected, f"rows={len(queue)}")
    untouched = sum(1 for q in queue if not q.get("last_refreshed_at"))
    check("every queue combo was touched", untouched == 0, f"{untouched} untouched")

    # -- fresh hits --------------------------------------------------------
    combo = grid[0]
    status, entry = db.get_cache_entry(
        combo["role"], combo["site"], "", combo["state"], combo["country"],
        combo["internship_mode"], combo["hours_old"],
        ttl_hours=config.CACHE_TTL_HOURS, min_volume=config.CACHE_MIN_VOLUME,
    )
    check("get_cache_entry is fresh after pass 1", status == "fresh",
          f"status={status}, jobs={len(entry['jobs']) if entry else 0}")

    # -- pass 2 no-op ------------------------------------------------------
    warmed2 = scheduler.run_prewarm()
    check("pass 2 warms nothing (all fresh)", warmed2 == 0, f"warmed={warmed2}")

    # -- leader lock -------------------------------------------------------
    with db._get_conn() as (conn, cur):
        owner = cur.execute("SELECT owner FROM scheduler_lock WHERE id = 1").fetchone()
    check("we own the scheduler lock", bool(owner) and owner["owner"] == scheduler._OWNER,
          owner["owner"] if owner else "none")

    # -- prewarm writes cache only ----------------------------------------
    with db._get_conn() as (conn, cur):
        job_rows = cur.execute("SELECT COUNT(*) AS c FROM jobs").fetchone()["c"]
    check("jobs table untouched by prewarm", job_rows == 0, f"rows={job_rows}")

    print("\n== result:", "ALL CHECKS PASSED" if all(c for _, c, _ in results) else "SOME CHECKS FAILED")
    return 0 if all(c for _, c, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())

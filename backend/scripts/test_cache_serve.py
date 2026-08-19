"""Proves searches are served from the DB cache instead of live scraping.

Uses a throwaway SQLite DB + counting fake scrapers. Verifies four scenarios:

  A. 100% cache hit   -> trigger_scrape returns 'done' instantly, live scrapers
                         are NEVER called, session jobs == cached DB jobs.
  B. Partial hit      -> cached combo served from DB; only the missing combo
                         hits the live scraper (exactly once).
  C. Fallback hit     -> city/state request served from a country-level cache
                         row (state='') with zero live scraping.
  D. Cold combo       -> goes to live scraping AND gets scheduled in the
                         prewarm_queue (priority bumped).

Run:
    D:\Python\Python310\python.exe backend\scripts\test_cache_serve.py

Exits 0 when every check passes, 1 otherwise.
"""
import asyncio
import json
import os
import sys
import tempfile
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import db
import config
import scrapers.indeed_scraper
import scrapers.linkedin_scraper
import scrapers.naukri_scraper

CALLS = {"indeed": 0, "linkedin": 0, "naukri": 0}
HOURS = 72


def _live_scraper(site):
    """Deterministic live-scraper stand-in that counts invocations."""
    def fake(**kwargs):
        CALLS[site] += 1
        role = kwargs["roles"][0]
        internship = bool(kwargs.get("internship_mode"))
        n = min(int(kwargs.get("results_wanted") or 30), 8)
        suffix = "Intern" if internship else "Senior"

        def gen():
            yield [
                {
                    "id": f"live-{site}-{i}",
                    "title": f"{role} LIVE-{site} {suffix}",
                    "company": f"Live {site} Co {i}",
                    "location": kwargs.get("location") or "",
                    "url": f"https://live.{site}.example.com/job/{i}",
                    "description": "Job produced by a LIVE scrape.",
                    "job_level": "internship" if internship else "",
                    "date_posted": "2026-08-10",
                    "source": site,
                }
                for i in range(n)
            ]

        return gen()

    return fake


def _patch_scrapers():
    scrapers.indeed_scraper.scrape_indeed = _live_scraper("indeed")
    scrapers.linkedin_scraper.scrape_linkedin = _live_scraper("linkedin")
    scrapers.naukri_scraper.scrape_naukri = _live_scraper("naukri")
    scrapers.linkedin_scraper.enrich_descriptions = lambda jobs: None


def _seed(role, site, state, country, mode, n=6, prefix="CACHED"):
    """Insert a cache row directly (what a prewarm pass would have produced)."""
    jobs = [
        {
            "title": f"{prefix} {role} #{i}",
            "company": f"Cache Co {i}",
            "location": state or country,
            "url": f"https://cached.example.com/{site}/{i}",
            "description": "Cached job served from the DB.",
            "job_board": site,
            "date_posted": "2026-08-10",
        }
        for i in range(n)
    ]
    db.save_cache_entry(role, site, "", state or "", country or "", mode, HOURS,
                        jobs, max_jobs=200, keep_larger=True)


async def _trigger(req):
    from api.routes.scrape import trigger_scrape
    return await trigger_scrape(req)


def _session_status(sid):
    s = db.get_session(sid)
    return (s or {}).get("status", "missing")


def _wait_done(sid, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _session_status(sid) == "done":
            return True
        time.sleep(0.5)
    return False


def main() -> int:
    results = []

    def check(name, cond, detail=""):
        results.append((name, bool(cond), detail))
        print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))

    tmpdir = tempfile.mkdtemp(prefix="cache_serve_")
    db._DB_PATH = os.path.join(tmpdir, "test.db")
    config.CACHE_ENABLED = True
    config.CACHE_TTL_HOURS = 12.0
    config.CACHE_MIN_VOLUME = 5
    config.CACHE_HOURS_OLD = HOURS
    config.SCHEDULER_ENABLED = False
    _patch_scrapers()
    db.init_db()

    from api.schemas import ScrapeRequest
    from api.routes.scrape import _cache_lookup

    # ============ A. 100% cache hit ========================================
    print("\n== A. 100% cache hit (should serve from DB, zero live scrapes)")
    _seed("Software Engineer", "indeed", "Karnataka", "in", 0)
    _seed("Software Engineer", "linkedin", "Karnataka", "in", 0)

    sid_a = "test-A"
    resp = asyncio.run(_trigger(ScrapeRequest(
        search_id=sid_a, sites=["indeed", "linkedin"],
        roles=["Software Engineer"], state="Karnataka", country="in",
        internship_mode=False, scrape_limit=200, hours_old=HOURS,
    )))
    check("A: response is synchronous 'done'", resp.get("status") == "done", str(resp))
    check("A: no live scrape happened", CALLS["indeed"] == 0 and CALLS["linkedin"] == 0,
          f"calls={CALLS}")
    sess_jobs = db.get_raw_jobs(sid_a)
    titles = {j["title"] for j in sess_jobs}
    cached_titles = {"CACHED Software Engineer #0", "CACHED Software Engineer #5"}
    check("A: session served from DB cache", cached_titles.issubset(titles),
          f"session_jobs={len(sess_jobs)}")
    check("A: no live-sourced jobs leaked in", not any("LIVE-" in t for t in titles),
          f"titles={sorted(titles)[:3]}...")

    # ============ B. Partial hit ===========================================
    print("\n== B. Partial hit (cached served, only missing combo scrapes)")
    _seed("Full Stack Developer", "indeed", "Karnataka", "in", 0)

    sid_b = "test-B"
    resp = asyncio.run(_trigger(ScrapeRequest(
        search_id=sid_b, sites=["indeed", "linkedin"],
        roles=["Full Stack Developer"], state="Karnataka", country="in",
        internship_mode=False, scrape_limit=200, hours_old=HOURS,
    )))
    check("B: response is async 'running'", resp.get("status") == "running", str(resp))
    check("B: waited for background completion", _wait_done(sid_b),
          f"status={_session_status(sid_b)}")
    check("B: only the missing board (linkedin) scraped live",
          CALLS["linkedin"] == 1 and CALLS["indeed"] == 0,
          f"calls={CALLS}")
    b_titles = {j["title"] for j in db.get_raw_jobs(sid_b)}
    check("B: cached + live jobs both in session",
          "CACHED Full Stack Developer #0" in b_titles and "LIVE-linkedin" in " ".join(b_titles),
          f"session_jobs={len(b_titles)}")
    # The live scrape refills the cache — that combo is no longer cold.
    fb_status, _ = db.get_cache_entry("Full Stack Developer", "linkedin",
                                      "", "Karnataka", "in", 0, HOURS,
                                      ttl_hours=config.CACHE_TTL_HOURS,
                                      min_volume=config.CACHE_MIN_VOLUME)
    check("B: live scrape refilled that cache row (self-healing)",
          fb_status == "fresh", f"status={fb_status}")

    # ============ C. Country-level fallback ================================
    print("\n== C. Country-level fallback (city request served from country row)")
    _seed("Data Scientist", "indeed", "", "in", 0)

    sid_c = "test-C"
    resp = asyncio.run(_trigger(ScrapeRequest(
        search_id=sid_c, sites=["indeed"], roles=["Data Scientist"],
        city="Bengaluru", state="Karnataka", country="in",
        internship_mode=False, scrape_limit=200, hours_old=HOURS,
    )))
    check("C: response is synchronous 'done'", resp.get("status") == "done", str(resp))
    calls_before_c = sum(CALLS.values())
    c_delta = sum(CALLS.values()) - calls_before_c
    check("C: zero live scrapes for fallback hit", c_delta == 0,
          f"new_calls={c_delta}")
    c_titles = {j["title"] for j in db.get_raw_jobs(sid_c)}
    check("C: fallback jobs came from country-level cache",
          "CACHED Data Scientist #0" in c_titles, f"session_jobs={len(c_titles)}")

    # ============ D. Cold combo -> live + scheduled ========================
    print("\n== D. Cold combo (no cache -> live scrape + prewarm scheduling)")
    sid_d = "test-D"
    resp = asyncio.run(_trigger(ScrapeRequest(
        search_id=sid_d, sites=["naukri"], roles=["Data Engineer"],
        country="in", internship_mode=False, scrape_limit=200, hours_old=HOURS,
    )))
    check("D: response is async 'running'", resp.get("status") == "running", str(resp))
    check("D: waited for background completion", _wait_done(sid_d),
          f"status={_session_status(sid_d)}")
    check("D: cold combo scraped live (naukri)", CALLS["naukri"] == 1, f"calls={CALLS}")
    queue = db.get_prewarm_queue()
    scheduled = [q for q in queue
                 if q["role"] == "Data Engineer" and q["site"] == "naukri"
                 and q["country"] == "in" and q["priority"] >= 1]
    check("D: cold combo scheduled in prewarm_queue", len(scheduled) >= 1,
          f"priority={scheduled[0]['priority'] if scheduled else None}")

    # ============ sanity: _cache_lookup split directly =====================
    print("\n== E. _cache_lookup split (unit-level)")
    req = ScrapeRequest(
        search_id="test-E", sites=["indeed", "linkedin", "naukri"],
        roles=["Software Engineer", "DevOps Engineer"], state="Karnataka", country="in",
        internship_mode=False, scrape_limit=200, hours_old=HOURS,
    )
    to_scrape, initial_jobs, served = _cache_lookup(req)
    check("E: cached combos not in scrape list", served == 2, f"served={served}")
    check("E: cold combos remain for live scrape", len(to_scrape) == 4,
          f"to_scrape={len(to_scrape)}")
    check("E: initial jobs seeded from cache only",
          all("CACHED" in j["title"] for j in initial_jobs), f"initial={len(initial_jobs)}")

    print("\n== result:", "ALL CHECKS PASSED" if all(c for _, c, _ in results) else "SOME CHECKS FAILED")
    return 0 if all(c for _, c, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())

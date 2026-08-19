"""City-loop unit tests for state-level Naukri combos.

Verifies that a Naukri combo with a state but no city loops the state's
curated cities (+ optional state term), merges all jobs under the state cache
key, dedupes across cities, and tags each job with searched_city.

Run (from anywhere):

    D:\Python\Python310\python.exe backend\scripts\test_city_loop.py

Uses a temp DB and a fake scraper — the real job_agent.db is never touched.
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
import api.routes.scrape as scrape_mod
import scrapers.naukri_scraper

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append(bool(cond))
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


def main() -> int:
    tmpdir = tempfile.mkdtemp(prefix="city_loop_")
    db._DB_PATH = os.path.join(tmpdir, "test.db")
    db.init_db()

    # -- helper: curated hit / unknown / empty -------------------------------
    cities = scrape_mod._state_cities("Andaman and Nicobar Islands", "in")
    check("curated state returns its city list", len(cities) == 5, str(cities))
    check("unknown state returns [] (status quo)", scrape_mod._state_cities("Narnia") == [])
    check("empty state returns []", scrape_mod._state_cities("") == [])

    # -- city loop via _scrape_combos ----------------------------------------
    calls = []

    def fake_naukri(**kwargs):
        calls.append(kwargs.get("location"))
        city = kwargs.get("location") or "x"
        role = kwargs["roles"][0]
        n = min(int(kwargs.get("results_wanted") or 30), 3)
        return [
            {
                "id": f"n-{city}-{i}",
                "title": f"{role} Senior",
                "company": f"C-{city}",
                "location": city,
                "url": f"https://naukri.example.com/jobs/{role}-{city}-{i}",
                "description": "Requires 5+ years of experience.",
                "date_posted": "2026-08-10",
                "job_level": "",
            }
            for i in range(n)
        ]

    scrapers.naukri_scraper.scrape_naukri = fake_naukri

    combo = {
        "role": "Data Analyst", "site": "naukri", "location": "Karnataka",
        "city": "", "state": "Karnataka", "country": "in",
        "indeed_country": "USA", "results_wanted": 30,
    }
    all_jobs, seen = scrape_mod._scrape_combos(
        None, [combo], keywords=[], internship_mode=False, hours_old=168,
        scrape_limit=30, stagger=(0, 0),
    )

    kc = config.CACHE_STATE_CITIES["Karnataka"][:config.CACHE_CITIES_PER_STATE]
    expected_locs = kc + (["Karnataka"] if config.CACHE_CITY_INCLUDE_STATE_TERM else [])
    check("scraper called once per city (+ state term)", calls == expected_locs, str(calls))

    with db._get_conn() as (conn, cur):
        row = cur.execute(
            "SELECT job_count, jobs_json FROM job_cache "
            "WHERE role='Data Analyst' AND site='naukri' AND "
            "state='Karnataka' AND country='in'"
        ).fetchone()
    check("results merged under the state key", row is not None)

    jobs = json.loads(row["jobs_json"]) if row else []
    expected_jobs = len(expected_locs) * 3
    check("jobs merged from every city", len(jobs) == expected_jobs, f"{len(jobs)}/{expected_jobs}")
    check("every job tagged with searched_city", all(j.get("searched_city") for j in jobs))
    check("searched_city values are real loop locations",
          all(j["searched_city"] in expected_locs for j in jobs))

    # A same-URL job appearing in two cities must dedup to one.
    scrapers.naukri_scraper.scrape_naukri = lambda **kw: [{
        "id": "dup", "title": "Data Analyst Senior", "company": "DupCorp",
        "location": kw.get("location"), "url": "https://naukri.example.com/jobs/same-url",
        "description": "Dup description.", "date_posted": "2026-08-10", "job_level": "",
    }]
    dup_all, _ = scrape_mod._scrape_combos(
        None, [combo], keywords=[], internship_mode=False, hours_old=168,
        scrape_limit=30, stagger=(0, 0),
    )
    check("cross-city dedup keeps one copy", len(dup_all) == 1, f"{len(dup_all)}")

    # -- location filter: nationwide fallback skipped, local kept ------------
    # Fake scraper: Bengaluru run returns "Gurugram" (nationwide fallback),
    # Mysuru run returns "Mysuru" (genuinely local). Prewarm filter should
    # drop Bengaluru batch and keep Mysuru.
    nationwide_seen = []

    def fake_nationwide(**kwargs):
        loc = kwargs.get("location", "")
        nationwide_seen.append(loc)
        if loc == "Bengaluru":
            # nationwide fallback: no mention of Bengaluru in locations
            return [{"id": "nb1", "title": "Data Analyst Senior", "company": "Fake",
                     "location": "Gurugram, Noida", "url": "https://naukri.example.com/nb1",
                     "description": "Nationwide fallback.", "date_posted": "2026-08-10", "job_level": ""}]
        else:
            # Mysuru: genuinely local
            return [{"id": "ml1", "title": "Data Analyst Senior", "company": "Fake",
                     "location": "Mysuru", "url": "https://naukri.example.com/ml1",
                     "description": "Genuinely local.", "date_posted": "2026-08-10", "job_level": ""}]

    scrapers.naukri_scraper.scrape_naukri = fake_nationwide
    with db._get_conn() as (conn, cur):
        cur.execute("DELETE FROM job_cache")
    filter_all, _ = scrape_mod._scrape_combos(
        None, [combo], keywords=[], internship_mode=False, hours_old=168,
        scrape_limit=30, stagger=(0, 0),
    )
    check("nationwide fallback skipped for Bengaluru",
          "Bengaluru" not in nationwide_seen or all(j.get("searched_city") != "Bengaluru" for j in filter_all),
          f"jobs={len(filter_all)}")
    check("genuinely local Mysuru jobs kept",
          any(j.get("searched_city") == "Mysuru" for j in filter_all),
          f"jobs={len(filter_all)}")

    print("\n== result:", "ALL CHECKS PASSED" if all(RESULTS) else "SOME CHECKS FAILED")
    return 0 if all(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())

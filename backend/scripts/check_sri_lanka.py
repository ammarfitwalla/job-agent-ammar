"""Standalone check: do we actually get jobs when someone searches Sri Lanka?

Mirrors the production path for a location-country search ("Sri Lanka"):
  - location resolution (country_code -> lk)
  - per-site board location token (_board_location)
  - existing cache entries for lk (have we EVER stored Sri Lankan jobs?)
  - live scrape via the real scrapers, using the same combos/filters as
    api.routes.scrape._scrape_combos

Run:
    D:\Python\Python310\python.exe backend\scripts\check_sri_lanka.py

The real config is imported (job_agent.db is read-only here - no writes).
"""
import os
import sys
import json

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import config
import db
import api.routes.scrape as scrape_mod
from api.schemas import ScrapeRequest

USE_TEMP_DB_FOR_SCRAPE = True  # keep the real job_agent.db pristine

LOCATION = "Sri Lanka"
ROLE = "Software Developer"
RESULTS_WANTED = 15
HOURS_OLD = 168


def main() -> int:
    print(f"== Check: jobs for '{LOCATION}' | role='{ROLE}' "
          f"results_wanted={RESULTS_WANTED} hours_old={HOURS_OLD} ==\n")

    # ---- 1) Location resolution (same as /api/scrape does) ----------------
    req = ScrapeRequest(search_id="check-srilanka", sites=["indeed", "linkedin", "naukri"],
                        roles=[ROLE], location=LOCATION,
                        indeed_country="Sri Lanka", results_wanted=RESULTS_WANTED,
                        hours_old=HOURS_OLD)
    scrape_mod._resolve_request_location(req)
    print(f"[1] Resolved location -> city={req.city!r} state={req.state!r} "
          f"country={req.country!r} indeed_country={req.indeed_country!r}")

    if not req.country:
        print("    WARNING: country not resolved - search will not key as a country search.")

    # ---- 2) What location token each board will actually search -----------
    print("\n[2] Board location tokens (_board_location):")
    for site in ("indeed", "linkedin", "naukri"):
        combo = {"role": ROLE, "site": site, "location": req.location,
                 "indeed_country": req.indeed_country,
                 "city": req.city, "state": req.state, "country": req.country}
        tok = scrape_mod._board_location(site, combo)
        print(f"    {site:9s} -> {tok!r}")

    # ---- 3) Cache: have we ever stored Sri Lanka jobs? --------------------
    print("\n[3] DB cache for country='lk' (existing stored jobs):")
    any_cache = False
    try:
        with db._get_conn() as (conn, cur):
            cur.execute("SELECT COUNT(*) FROM job_cache WHERE country='lk'")
            n = cur.fetchone()[0]
            cur.execute("SELECT role, site, city, state, country, job_count FROM job_cache "
                        "WHERE country='lk' ORDER BY job_count DESC LIMIT 10")
            rows = cur.fetchall()
        if n:
            any_cache = True
        print(f"    {n} cache entry(ies).")
        for r in rows:
            print(f"      role={r[0]} site={r[1]} city={r[2]!r} state={r[3]!r} jobs={r[5]}")
        if not n:
            print("    (none - Sri Lanka has never produced a cache entry)")
    except Exception as e:
        print(f"    cache query failed: {e}")

    try:
        with db._get_conn() as (conn, cur):
            cur.execute("SELECT COUNT(*) FROM sessions WHERE LOWER(COALESCE(location,'')) LIKE '%sri lanka%'")
            s = cur.fetchone()[0]
        print(f"    past sessions mentioning 'sri lanka': {s}")
        if s:
            any_cache = True
    except Exception as e:
        print(f"    sessions query failed: {e}")

    # ---- 4) Live scrape through the production pipeline -------------------
    if USE_TEMP_DB_FOR_SCRAPE:
        import tempfile
        db._DB_PATH = os.path.join(tempfile.mkdtemp(prefix="lk_check_"), "scratch.db")
        db.init_db()
        print(f"\n[4] Live scrape (temp DB: {db._DB_PATH})...")
    else:
        print(f"\n[4] Live scrape (real DB {db._DB_PATH})...")
    combos = [{"role": ROLE, "site": site, "location": req.location,
               "indeed_country": req.indeed_country,
               "city": req.city, "state": req.state, "country": req.country}
              for site in req.sites]
    try:
        all_jobs, _seen = scrape_mod._scrape_combos(
            None, combos, keywords=[], internship_mode=False,
            hours_old=HOURS_OLD, scrape_limit=RESULTS_WANTED, stagger=(0, 0),
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        all_jobs, _seen = [], set()

    print(f"    total jobs returned by pipeline: {len(all_jobs)}")
    from collections import Counter
    by_site = Counter(j.get("job_board") for j in all_jobs)
    for site, cnt in by_site.items():
        print(f"      {site}: {cnt}")
    sri_lanka_locs = [j.get("location") for j in all_jobs
                      if "sri lanka" in (j.get("location") or "").lower()]
    print(f"    jobs whose location mentions Sri Lanka: {len(sri_lanka_locs)}")
    for j in all_jobs[:8]:
        print(f"      - {j.get('title')} | {j.get('company')} | "
              f"{(j.get('location') or '')[:50]} | {j.get('url','')[:70]}")

    if all_jobs and not any_cache:
        print("\n== RESULT: Sri Lanka returns jobs live, but nothing was ever cached "
              "(searches would still work but re-scrape each time).")
    elif all_jobs and any_cache:
        print("\n== RESULT: Sri Lanka returns jobs AND has been cached before.")
    elif not all_jobs and any_cache:
        print("\n== RESULT: Sri Lanka has cache entries but the live scrape (right now) "
              "returned nothing - likely a transient board block / no fresh postings.")
    else:
        print("\n== RESULT: No jobs returned and no cache history - Sri Lanka is effectively "
              "unsupported by the currently-wired scrapers.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
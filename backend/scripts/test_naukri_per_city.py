"""Tests for Naukri per-city cache distribution.

Verifies that:
1. State combos distribute nationwide results to per-city cache entries
2. Per-city combos tag jobs by actual location and distribute
3. Cross-city dedup works
4. _cache_lookup decomposes Naukri state searches into per-city lookups
5. Scheduler _grid_combos generates per-city combos for Naukri
6. Nationwide results with recognized cities are distributed to per-city entries
7. Remote jobs saved under city="", state="", is_remote=1
8. Unrecognized non-remote locations are skipped
9. is_remote column properly stored and queried

Run (from anywhere):

    python backend\\scripts\\test_naukri_per_city.py

Uses a temp DB and a fake scraper — the real job_agent.db is never touched.
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import db
import config
import api.routes.scrape as scrape_mod
import scheduler
import scrapers.naukri_scraper

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append(bool(cond))
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


def _make_job(title, company, city, url_id, location_override=None):
    """Helper to build a fake Naukri job."""
    return {
        "id": f"n-{url_id}",
        "title": title,
        "company": company,
        "location": location_override or city,
        "url": f"https://naukri.example.com/jobs/{url_id}",
        "description": "Requires 3+ years.",
        "date_posted": "2026-08-20",
        "job_level": "",
    }


def _seed_fresh(city, role="Data Analyst", state="Karnataka", country="in", n=12):
    """Seed a cache entry with enough jobs to be 'fresh' (>= min_volume)."""
    jobs = [_make_job(role, f"C-{city}", city, f"fresh-{city}-{i}") for i in range(n)]
    db.save_cache_entry(role, "naukri", city, state, country, False, 168, jobs)


def _clear_db():
    with db._get_conn() as (conn, cur):
        cur.execute("DELETE FROM job_cache")
        cur.execute("DELETE FROM prewarm_queue")
        conn.commit()
    # Clear the city-state map cache so tests don't pollute each other
    scrape_mod._city_state_map_cache.clear()


def main() -> int:
    tmpdir = tempfile.mkdtemp(prefix="naukri_per_city_")
    db._DB_PATH = os.path.join(tmpdir, "test.db")
    db.init_db()

    # Patch delay to be instant
    scrape_mod._delay = lambda *a, **kw: None
    # Also patch where _scrape_combos re-imports it
    import utils.delay
    utils.delay.delay = lambda *a, **kw: None

    # ────────────────────────────────────────────────────────────────────
    print("\n== TEST 1: State combo distributes nationwide results to per-city cache ==")
    # ────────────────────────────────────────────────────────────────────
    _clear_db()

    def fake_nationwide_scrape(**kwargs):
        city = kwargs.get("location", "")
        if city == "Bengaluru":
            return [
                _make_job("Data Analyst", "B Corp", "Bengaluru", "bl1"),
                _make_job("Data Analyst", "B Corp", "Bengaluru", "bl2",
                          location_override="Bengaluru, Karnataka"),
                _make_job("Data Analyst", "Nationwide Corp", "Gurugram", "gur1",
                          location_override="Gurugram, Haryana"),
            ]
        elif city == "Mysuru":
            return [
                _make_job("Data Analyst", "M Corp", "Mysuru", "ms1"),
                _make_job("Data Analyst", "Capital Corp", "New Delhi", "dl1",
                          location_override="New Delhi, Delhi"),
            ]
        return []

    scrapers.naukri_scraper.scrape_naukri = fake_nationwide_scrape

    state_combo = {
        "role": "Data Analyst", "site": "naukri", "location": "Karnataka",
        "city": "", "state": "Karnataka", "country": "in",
        "indeed_country": "India", "results_wanted": 30,
    }
    all_jobs, seen = scrape_mod._scrape_combos(
        None, [state_combo], keywords=[], internship_mode=False, hours_old=168,
        scrape_limit=30, stagger=(0, 0),
    )

    # Check per-city cache entries (query across ALL states, not just Karnataka)
    with db._get_conn() as (conn, cur):
        rows = cur.execute(
            "SELECT city, state, job_count, jobs_json FROM job_cache "
            "WHERE role='Data Analyst' AND site='naukri' AND country='in'"
        ).fetchall()

    city_entries = {}
    for r in rows:
        city_entries[f"{r['state']}/{r['city']}"] = r

    check("per-city cache entries created",
          len(city_entries) >= 4,
          f"entries: {list(city_entries.keys())}")

    bl_entry = city_entries.get("Karnataka/Bengaluru")
    if bl_entry:
        bl_jobs = json.loads(bl_entry["jobs_json"])
        check("Bengaluru entry has 2 jobs", len(bl_jobs) == 2,
              f"got {len(bl_jobs)}: {[j.get('url') for j in bl_jobs]}")
    else:
        check("Bengaluru entry exists", False, f"keys={list(city_entries.keys())}")

    ms_entry = city_entries.get("Karnataka/Mysuru")
    if ms_entry:
        ms_jobs = json.loads(ms_entry["jobs_json"])
        check("Mysuru entry has 1 job", len(ms_jobs) == 1,
              f"got {len(ms_jobs)}: {[j.get('url') for j in ms_jobs]}")
    else:
        check("Mysuru entry exists", False, f"keys={list(city_entries.keys())}")

    gur_entry = city_entries.get("Haryana/Gurugram")
    if gur_entry:
        gur_jobs = json.loads(gur_entry["jobs_json"])
        check("Gurugram nationwide job distributed to its city/state",
              len(gur_jobs) == 1 and gur_entry["state"] == "Haryana",
              f"state={gur_entry['state']}, count={len(gur_jobs)}")
    else:
        check("Gurugram nationwide job distributed to its city/state", False,
              f"no Haryana/Gurugram entry, keys={list(city_entries.keys())}")

    dl_entry = city_entries.get("Delhi/New Delhi")
    if dl_entry:
        dl_jobs = json.loads(dl_entry["jobs_json"])
        check("Delhi nationwide job distributed to its city/state",
              len(dl_jobs) == 1 and dl_entry["state"] == "Delhi",
              f"state={dl_entry['state']}, count={len(dl_jobs)}")
    else:
        check("Delhi nationwide job distributed to its city/state", False,
              f"no Delhi/New Delhi entry, keys={list(city_entries.keys())}")

    check("all_jobs contains all 5 jobs", len(all_jobs) == 5,
          f"got {len(all_jobs)}")

    # ────────────────────────────────────────────────────────────────────
    print("\n== TEST 2: Per-city combo tags and distributes nationwide results ==")
    # ────────────────────────────────────────────────────────────────────
    _clear_db()

    city_combo = {
        "role": "Data Analyst", "site": "naukri", "location": "Bengaluru",
        "city": "Bengaluru", "state": "Karnataka", "country": "in",
        "indeed_country": "India", "results_wanted": 30,
    }

    def fake_city_scrape(**kwargs):
        return [
            _make_job("Data Analyst", "Local", "Bengaluru", "city-bl1"),
            _make_job("Data Analyst", "Remote", "Mumbai", "city-mum1"),
        ]

    scrapers.naukri_scraper.scrape_naukri = fake_city_scrape
    city_jobs, _ = scrape_mod._scrape_combos(
        None, [city_combo], keywords=[], internship_mode=False, hours_old=168,
        scrape_limit=30, stagger=(0, 0),
    )
    check("per-city combo keeps jobs with recognized locations",
          len(city_jobs) == 2,
          f"got {len(city_jobs)}: {[j.get('location') for j in city_jobs]}")

    # Verify per-city cache entries
    with db._get_conn() as (conn, cur):
        rows = cur.execute(
            "SELECT city, state, job_count, jobs_json FROM job_cache "
            "WHERE role='Data Analyst' AND site='naukri' AND country='in'"
        ).fetchall()

    city_entries2 = {}
    for r in rows:
        city_entries2[f"{r['state']}/{r['city']}"] = r

    check("per-city cache has Bengaluru entry",
          "Karnataka/Bengaluru" in city_entries2,
          f"keys={list(city_entries2.keys())}")
    check("per-city cache has Mumbai entry",
          "Maharashtra/Mumbai" in city_entries2,
          f"keys={list(city_entries2.keys())}")

    if "Maharashtra/Mumbai" in city_entries2:
        mum_jobs = json.loads(city_entries2["Maharashtra/Mumbai"]["jobs_json"])
        check("Mumbai entry has 1 job",
              len(mum_jobs) == 1 and "Mumbai" in mum_jobs[0].get("location", ""),
              f"count={len(mum_jobs)}, loc={mum_jobs[0].get('location') if mum_jobs else 'none'}")

    # ────────────────────────────────────────────────────────────────────
    print("\n== TEST 3: Cross-city dedup ==")
    # ────────────────────────────────────────────────────────────────────
    _clear_db()

    def fake_dup_scrape(**kwargs):
        city = kwargs.get("location", "")
        return [_make_job("Data Analyst", "DupCorp", city, "dedup-same",
                          location_override=city)]

    scrapers.naukri_scraper.scrape_naukri = fake_dup_scrape

    state_combo2 = {
        "role": "Data Analyst", "site": "naukri", "location": "Karnataka",
        "city": "", "state": "Karnataka", "country": "in",
        "indeed_country": "India", "results_wanted": 30,
    }
    dup_jobs, _ = scrape_mod._scrape_combos(
        None, [state_combo2], keywords=[], internship_mode=False, hours_old=168,
        scrape_limit=30, stagger=(0, 0),
    )
    check("cross-city dedup keeps one copy in all_jobs",
          len(dup_jobs) == 1, f"got {len(dup_jobs)}")
    with db._get_conn() as (conn, cur):
        rows = cur.execute(
            "SELECT city, job_count FROM job_cache "
            "WHERE role='Data Analyst' AND site='naukri' AND state='Karnataka'"
        ).fetchall()
    total_cached = sum(r["job_count"] for r in rows)
    check("per-city cache entries have jobs from each city",
          total_cached >= 2, f"total cached: {total_cached}")

    # ────────────────────────────────────────────────────────────────────
    print("\n== TEST 4: _cache_lookup decomposes Naukri state into per-city lookups ==")
    # ────────────────────────────────────────────────────────────────────
    _clear_db()

    # Seed 2 fresh cities with >= min_volume jobs
    for city in ["Bengaluru", "Mysuru"]:
        _seed_fresh(city)

    class MockReq:
        roles = ["Data Analyst"]
        sites = ["naukri"]
        city = ""
        state = "Karnataka"
        country = "in"
        internship_mode = False
        hours_old = 168
        location = "Karnataka"
        indeed_country = "India"
        scrape_limit = 30

    req = MockReq()
    combos, initial, served = scrape_mod._cache_lookup(req)

    check("fresh cities served from cache", served >= 2, f"served={served}")
    check("initial_jobs has cached jobs", len(initial) >= 20,
          f"initial={len(initial)} (expect >=20 from 2 cities x12)")

    scrape_cities = [c["city"] for c in combos if c.get("city")]
    check("missing cities returned for scraping",
          len(scrape_cities) > 0, f"to_scrape={scrape_cities}")
    state_combos = [c for c in combos if not c.get("city")]
    check("no state-level combo in scrape list when some cities exist",
          len(state_combos) == 0, f"state_combos={len(state_combos)}")
    check("Bengaluru not re-scraped (fresh)",
          "Bengaluru" not in scrape_cities, f"scrape_cities={scrape_cities}")
    check("Mysuru not re-scraped (fresh)",
          "Mysuru" not in scrape_cities, f"scrape_cities={scrape_cities}")
    # The remaining 3 should be in scrape list
    remaining = set(scrape_cities)
    check("Hubballi/Mangaluru/Belagavi need scraping",
          remaining == {"Hubballi", "Mangaluru", "Belagavi"},
          f"remaining={remaining}")

    # ────────────────────────────────────────────────────────────────────
    print("\n== TEST 5: _cache_lookup all-missing falls back to state combo ==")
    # ────────────────────────────────────────────────────────────────────
    _clear_db()

    combos2, initial2, served2 = scrape_mod._cache_lookup(MockReq())
    check("all-missing: no cache served", served2 == 0, f"served={served2}")
    check("all-missing: state-level combo returned for full city loop",
          any(not c.get("city") for c in combos2),
          f"combos={[(c.get('city'), c.get('state')) for c in combos2]}")

    # ────────────────────────────────────────────────────────────────────
    print("\n== TEST 6: Scheduler _grid_combos generates per-city for Naukri ==")
    # ────────────────────────────────────────────────────────────────────
    # Naukri is only in CACHE_SITES_INDIA, so use country="in"
    original_cities = config.CACHE_STATE_CITIES.get("Testland", None)
    config.CACHE_STATE_CITIES["Testland"] = ["CityA", "CityB"]

    original_roles = config.CACHE_ROLES[:]
    original_countries = config.CACHE_COUNTRIES[:]
    original_include = config.CACHE_INCLUDE_ALL_STATES
    original_override = dict(config.CACHE_STATES_OVERRIDE)
    original_india_sites = config.CACHE_SITES_INDIA[:]
    original_default_sites = config.CACHE_SITES_DEFAULT[:]

    config.CACHE_ROLES = ["TestRole"]
    config.CACHE_COUNTRIES = ["in"]
    config.CACHE_INCLUDE_ALL_STATES = False
    config.CACHE_STATES_OVERRIDE["in"] = ["Testland"]
    # Ensure naukri is in the sites list for India
    config.CACHE_SITES_INDIA = ["indeed", "linkedin", "naukri"]

    try:
        grid = scheduler._grid_combos()
        naukri = [c for c in grid if c["site"] == "naukri" and c["state"] == "Testland"]
        non_naukri = [c for c in grid if c["site"] != "naukri" and c["state"] == "Testland"]

        check("Naukri grid has per-city combos",
              len(naukri) == 4, f"got {len(naukri)} (expect 2 cities x 2 modes)")
        check("Naukri combos have city set",
              all(c.get("city") for c in naukri),
              f"cities={[c['city'] for c in naukri]}")
        check("Non-Naukri combos still state-level",
              all(not c.get("city") for c in non_naukri),
              f"got {len(non_naukri)} state-level")

        grid_cities = {c["city"] for c in naukri}
        check("Both curated cities present in grid",
              grid_cities == {"CityA", "CityB"},
              f"grid_cities={grid_cities}")
    finally:
        if original_cities is not None:
            config.CACHE_STATE_CITIES["Testland"] = original_cities
        else:
            config.CACHE_STATE_CITIES.pop("Testland", None)
        config.CACHE_ROLES = original_roles
        config.CACHE_COUNTRIES = original_countries
        config.CACHE_INCLUDE_ALL_STATES = original_include
        config.CACHE_STATES_OVERRIDE.clear()
        config.CACHE_STATES_OVERRIDE.update(original_override)
        config.CACHE_SITES_INDIA = original_india_sites
        config.CACHE_SITES_DEFAULT = original_default_sites

    # ────────────────────────────────────────────────────────────────────
    print("\n== TEST 7: Nationwide results with 0 local matches no longer skipped ==")
    # ────────────────────────────────────────────────────────────────────
    _clear_db()

    def fake_zero_local(**kwargs):
        city = kwargs.get("location", "")
        if city == "Bengaluru":
            return [_make_job("Data Analyst", "FarAway", "Mumbai", "zeroloc1",
                              location_override="Mumbai, Maharashtra")]
        return []

    scrapers.naukri_scraper.scrape_naukri = fake_zero_local

    zero_combo = {
        "role": "Data Analyst", "site": "naukri", "location": "Karnataka",
        "city": "", "state": "Karnataka", "country": "in",
        "indeed_country": "India", "results_wanted": 30,
    }
    zero_jobs, _ = scrape_mod._scrape_combos(
        None, [zero_combo], keywords=[], internship_mode=False, hours_old=168,
        scrape_limit=30, stagger=(0, 0),
    )
    check("nationwide results kept (not discarded)",
          len(zero_jobs) == 1, f"got {len(zero_jobs)}")

    with db._get_conn() as (conn, cur):
        row = cur.execute(
            "SELECT city, state, jobs_json FROM job_cache "
            "WHERE role='Data Analyst' AND site='naukri' AND city='Mumbai'"
        ).fetchone()
    if row:
        cached = json.loads(row["jobs_json"])
        check("zero-local job saved to Mumbai/Maharashtra cache",
              row["state"] == "Maharashtra" and any("Mumbai" in j.get("location", "") for j in cached),
              f"city={row['city']}, state={row['state']}")
    else:
        check("zero-local job saved to cache", False, "no Mumbai entry found")

    # ────────────────────────────────────────────────────────────────────
    print("\n== TEST 8: Stale cities served + re-scraped ==")
    # ────────────────────────────────────────────────────────────────────
    _clear_db()

    # Seed Bengaluru as fresh, Mysuru as stale (old timestamp)
    _seed_fresh("Bengaluru")
    _seed_fresh("Mysuru")
    # Make Mysuru stale by backdating
    with db._get_conn() as (conn, cur):
        cur.execute(
            "UPDATE job_cache SET scraped_at = ? "
            "WHERE role='Data Analyst' AND site='naukri' AND city='Mysuru' AND state='Karnataka'",
            ((datetime.utcnow() - timedelta(hours=25)).isoformat(),),
        )
        conn.commit()
    scrape_mod._city_state_map_cache.clear()

    combos8, initial8, served8 = scrape_mod._cache_lookup(MockReq())
    check("stale+fresh cities: both served", served8 >= 2, f"served={served8}")
    check("stale+fresh: initial_jobs has jobs", len(initial8) >= 20,
          f"initial={len(initial8)}")
    scrape_cities8 = [c["city"] for c in combos8 if c.get("city")]
    check("Mysuru (stale) added for re-scraping",
          "Mysuru" in scrape_cities8, f"scrape_cities={scrape_cities8}")
    check("Bengaluru (fresh) NOT re-scraped",
          "Bengaluru" not in scrape_cities8, f"scrape_cities={scrape_cities8}")

    # ────────────────────────────────────────────────────────────────────
    print("\n== TEST 9: Remote jobs saved under city='', state='', is_remote=1 ==")
    # ────────────────────────────────────────────────────────────────────
    _clear_db()

    def fake_remote_scrape(**kwargs):
        city = kwargs.get("location", "")
        if city == "Bengaluru":
            return [
                _make_job("Data Analyst", "Local", "Bengaluru", "rem1"),
                _make_job("Data Analyst", "WFH Corp", "Remote", "rem2",
                          location_override="Remote - Work from Home"),
                _make_job("Data Analyst", "Hybrid Corp", "Bengaluru", "rem3",
                          location_override="Bengaluru (Remote)"),
            ]
        return []

    scrapers.naukri_scraper.scrape_naukri = fake_remote_scrape

    state_combo9 = {
        "role": "Data Analyst", "site": "naukri", "location": "Karnataka",
        "city": "", "state": "Karnataka", "country": "in",
        "indeed_country": "India", "results_wanted": 30,
    }
    remote_jobs, _ = scrape_mod._scrape_combos(
        None, [state_combo9], keywords=[], internship_mode=False, hours_old=168,
        scrape_limit=30, stagger=(0, 0),
    )
    check("remote + local jobs kept",
          len(remote_jobs) == 3, f"got {len(remote_jobs)}")

    with db._get_conn() as (conn, cur):
        # Check local job saved under Bengaluru
        bl_row = cur.execute(
            "SELECT city, state, is_remote, jobs_json FROM job_cache "
            "WHERE role='Data Analyst' AND site='naukri' AND city='Bengaluru' "
            "AND is_remote=0"
        ).fetchone()
        check("local job in Bengaluru cache with is_remote=0",
              bl_row is not None and bl_row["is_remote"] == 0,
              f"row={bl_row}")

        # Check remote job saved under city="", state="", is_remote=1
        rem_row = cur.execute(
            "SELECT city, state, is_remote, jobs_json FROM job_cache "
            "WHERE role='Data Analyst' AND site='naukri' AND is_remote=1"
        ).fetchone()
        check("remote job in remote cache entry (is_remote=1)",
              rem_row is not None and rem_row["city"] == "" and rem_row["is_remote"] == 1,
              f"row={rem_row}")
        if rem_row:
            rem_cached = json.loads(rem_row["jobs_json"])
            check("remote cache has 2 remote jobs (Remote + Bengaluru Remote)",
                  len(rem_cached) == 2,
                  f"count={len(rem_cached)}")

        # Check no entry for "Remote" city name
        bad_row = cur.execute(
            "SELECT city FROM job_cache "
            "WHERE role='Data Analyst' AND site='naukri' AND city='Remote'"
        ).fetchone()
        check("no cache entry with city='Remote'", bad_row is None)

    # ────────────────────────────────────────────────────────────────────
    print("\n== TEST 10: Unrecognized non-remote locations are skipped ==")
    # ────────────────────────────────────────────────────────────────────
    _clear_db()

    def fake_unknown_scrape(**kwargs):
        city = kwargs.get("location", "")
        if city == "Bengaluru":
            return [
                _make_job("Data Analyst", "Local", "Bengaluru", "unk1"),
                _make_job("Data Analyst", "Tiny Corp", "Some Random Village", "unk2",
                          location_override="Some Random Village, Unknown State"),
            ]
        return []

    scrapers.naukri_scraper.scrape_naukri = fake_unknown_scrape

    state_combo10 = {
        "role": "Data Analyst", "site": "naukri", "location": "Karnataka",
        "city": "", "state": "Karnataka", "country": "in",
        "indeed_country": "India", "results_wanted": 30,
    }
    unk_jobs, _ = scrape_mod._scrape_combos(
        None, [state_combo10], keywords=[], internship_mode=False, hours_old=168,
        scrape_limit=30, stagger=(0, 0),
    )
    check("unrecognized location skipped, only local job kept",
          len(unk_jobs) == 1, f"got {len(unk_jobs)}")

    with db._get_conn() as (conn, cur):
        rows = cur.execute(
            "SELECT city, is_remote, job_count FROM job_cache "
            "WHERE role='Data Analyst' AND site='naukri'"
        ).fetchall()
        total = sum(r["job_count"] for r in rows)
        check("only 1 job cached (unrecognized skipped)",
              total == 1, f"total={total}, rows={[(r['city'], r['is_remote']) for r in rows]}")

    # ────────────────────────────────────────────────────────────────────
    print("\n== TEST 11: Per-city combo skips non-matching non-remote jobs ==")
    # ────────────────────────────────────────────────────────────────────
    _clear_db()

    def fake_percity_skip_scrape(**kwargs):
        city = kwargs.get("location", "")
        if city == "Bengaluru":
            return [
                _make_job("Data Analyst", "Local", "Bengaluru", "skip1"),
                _make_job("Data Analyst", "Other State Corp", "Mumbai", "skip2",
                          location_override="Mumbai, Maharashtra"),
                _make_job("Data Analyst", "Unknown Corp", "Village", "skip3",
                          location_override="Unknown Village, Nowhere"),
            ]
        return []

    scrapers.naukri_scraper.scrape_naukri = fake_percity_skip_scrape

    city_combo11 = {
        "role": "Data Analyst", "site": "naukri", "location": "Bengaluru",
        "city": "Bengaluru", "state": "Karnataka", "country": "in",
        "indeed_country": "India", "results_wanted": 30,
    }
    pc_jobs, _ = scrape_mod._scrape_combos(
        None, [city_combo11], keywords=[], internship_mode=False, hours_old=168,
        scrape_limit=30, stagger=(0, 0),
    )
    check("per-city: local kept, Mumbai kept (recognized), unknown skipped",
          len(pc_jobs) == 2, f"got {len(pc_jobs)}")

    with db._get_conn() as (conn, cur):
        rows = cur.execute(
            "SELECT city, state, is_remote FROM job_cache "
            "WHERE role='Data Analyst' AND site='naukri'"
        ).fetchall()
        keys = {(r["city"], r["state"], r["is_remote"]) for r in rows}
        check("Bengaluru entry exists",
              ("Bengaluru", "Karnataka", 0) in keys, f"keys={keys}")
        check("Mumbai entry exists (recognized globally)",
              ("Mumbai", "Maharashtra", 0) in keys, f"keys={keys}")
        check("no 'Village' entry (unrecognized skipped)",
              not any("village" in k[0].lower() for k in keys), f"keys={keys}")

    # Cleanup
    scrapers.naukri_scraper.scrape_naukri = lambda **kw: []
    try:
        os.remove(db._DB_PATH)
    except OSError:
        pass
    db._DB_PATH = os.path.join(os.path.dirname(os.path.abspath(db.__file__)), "job_agent.db")

    print("\n== result:", "ALL CHECKS PASSED" if all(RESULTS) else "SOME CHECKS FAILED")
    return 0 if all(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())

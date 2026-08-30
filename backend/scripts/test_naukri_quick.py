"""Minimal test for Naukri per-city logic."""
import sys, os, tempfile, json

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import db
import api.routes.scrape as scrape_mod
import scrapers.naukri_scraper

def _job(title, company, loc, url_id):
    return {"id": url_id, "title": title, "company": company, "location": loc,
            "url": f"https://naukri.example.com/{url_id}", "description": "desc",
            "date_posted": "2026-08-20", "job_level": ""}

tmpdir = tempfile.mkdtemp(prefix="test_")
db._DB_PATH = os.path.join(tmpdir, "test.db")
db.init_db()

def fake(**kw):
    city = kw.get("location", "")
    if city == "Bengaluru":
        return [_job("DA", "B", "Bengaluru", "bl1"),
                _job("DA", "B", "Bengaluru, Karnataka", "bl2"),
                _job("DA", "N", "Gurugram, Haryana", "gur1")]
    elif city == "Mysuru":
        return [_job("DA", "M", "Mysuru", "ms1"),
                _job("DA", "C", "New Delhi, Delhi", "dl1")]
    return []

scrapers.naukri_scraper.scrape_naukri = fake

combo = {"role": "Data Analyst", "site": "naukri", "location": "Karnataka",
         "city": "", "state": "Karnataka", "country": "in",
         "indeed_country": "India", "results_wanted": 30}
print("Running _scrape_combos...")
all_jobs, seen = scrape_mod._scrape_combos(
    None, [combo], keywords=[], internship_mode=False, hours_old=168,
    scrape_limit=30, stagger=(0, 0))

print(f"all_jobs: {len(all_jobs)}")
with db._get_conn() as (conn, cur):
    rows = cur.execute(
        "SELECT city, job_count FROM job_cache "
        "WHERE role='Data Analyst' AND site='naukri' AND state='Karnataka'"
    ).fetchall()
    for r in rows:
        print(f"  cache city={r['city']} count={r['job_count']}")

print("DONE")

#!/usr/bin/env python3
"""Standalone read-only audit of cached job coverage for GCC countries.

Run from backend/ so db.py + config.py resolve:
    python scripts/gcc_audit.py
    python scripts/gcc_audit.py --db /path/to/job_agent.db
    python scripts/gcc_audit.py --roles "AI Engineer,Data Scientist"

Does not modify any data, config, or runtime logic.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db
from db import get_cache_entry, get_cached_jobs_aggregate

GCC = ["bh", "kw", "om", "qa", "sa", "ae"]
REFERENCE = ["in", "us"]
DEFAULT_ROLES = [
    "AI Engineer", "Data Scientist", "Data Analyst", "Machine Learning Engineer",
    "Software Engineer", "Full Stack Developer", "Backend Developer",
    "DevOps Engineer", "QA Engineer", "Data Engineer",
]


def _row_counts(cc):
    rows = {}
    with db._get_conn() as (conn, cur):
        for site in ("indeed", "linkedin", "naukri"):
            cur.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(job_count),0) AS jc "
                "FROM job_cache WHERE country=? AND site=? AND city='' AND state=''",
                (cc, site))
            r = cur.fetchone()
            rows[site] = {"national_rows": r["n"], "national_jobs": r["jc"]}
            cur.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(job_count),0) AS jc "
                "FROM job_cache WHERE country=? AND site=?",
                (cc, site))
            r = cur.fetchone()
            rows[site]["any_rows"] = r["n"]
            rows[site]["any_jobs"] = r["jc"]
    return rows


def _lookups(role, cc, site):
    s1, e1 = get_cache_entry(role, site, "", "", cc, False, 168)
    s2, e2 = get_cached_jobs_aggregate(role, site, "", "", cc, False, 168)
    return (s1, len(e1["jobs"]) if e1 else 0), (s2, len(e2["jobs"]) if e2 else 0)


def _fmt(status, n):
    return f"{status:<7}{n:>5}"


def main():
    ap = argparse.ArgumentParser(description="GCC cache coverage audit (read-only).")
    ap.add_argument("--db", default=None, help="Override sqlite DB path")
    ap.add_argument("--roles", default=",".join(DEFAULT_ROLES),
                    help="Comma-separated role list")
    ap.add_argument("--country", default="", help="Limit to one country code")
    ap.add_argument("--sites", default="indeed,linkedin,naukri",
                    help="Comma-separated site keys")
    args = ap.parse_args()

    if args.db:
        db._DB_PATH = os.path.abspath(args.db)
    roles = [r.strip() for r in args.roles.split(",") if r.strip()]
    sites = [s.strip() for s in args.sites.split(",") if s.strip()]
    countries = [c.strip() for c in args.country.split(",") if c.strip()] or (GCC + REFERENCE)

    print(f"DB: {db._DB_PATH}")
    try:
        import config
        print(f"config.CACHE_COUNTRIES = {config.CACHE_COUNTRIES}")
        missing = [c for c in GCC if c not in config.CACHE_COUNTRIES]
        print(f"GCC in prewarm grid: {[c for c in GCC if c in config.CACHE_COUNTRIES] or 'NONE'}"
              + (f"  -> missing: {missing} (background prewarm never scrapes these)" if missing else ""))
        print(f"config.CACHE_ROLES count = {len(config.CACHE_ROLES)}")
    except Exception:
        pass

    print("\n=== National-only rows & jobs in cache (city='' AND state='') per site ===")
    for cc in countries:
        rc = _row_counts(cc)
        parts = [f"{s}: nr={rc[s]['national_rows']} jobs={rc[s]['national_jobs']}"
                 for s in sites]
        print(f"  {cc.upper():<4} | " + " | ".join(parts))

    print("\n=== Exact vs Aggregate lookups (role x country x site) ===")
    for role in roles:
        print(f"\n[{role}]")
        print(f"  {'COUNTRY':<8} {'SITE':<9} {'ANY-ROWS(JC)':<16} {'EXACT':<15} {'AGGREGATE':<16}")
        for cc in countries:
            rc = _row_counts(cc)
            for site in sites:
                if site == "naukri" and cc != "in":
                    any_info = "-"
                    ex, ag = ("skip", 0), ("skip", 0)
                else:
                    a = rc[site]
                    any_info = f"{a['any_rows']}({a['any_jobs']})"
                    ex, ag = _lookups(role, cc, site)
                print(f"  {cc.upper():<8} {site:<9} {any_info:<16} "
                      f"{_fmt(ex[0], ex[1])} {_fmt(ag[0], ag[1])}")


if __name__ == "__main__":
    main()
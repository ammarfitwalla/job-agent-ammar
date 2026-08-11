"""Standalone test for the Indeed and LinkedIn scrapers.

Run from the backend directory:
    python test_scrapers.py --site indeed --role "Cloud Engineer" --location "New York, NY"
    python test_scrapers.py --site both --role "DevOps Engineer" --internship
    python test_scrapers.py --site linkedin --role "Software Engineer" --limit 30 --hours 168
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scrapers.indeed_scraper import scrape_indeed
from scrapers.linkedin_scraper import scrape_linkedin


def summarize(site: str, role: str, jobs: list):
    print(f"\n=== {site.upper()} — {len(jobs)} fetched for role '{role}' ===")
    if not jobs:
        print("  (no jobs)")
        return
    from match_engine.relevance_engine import role_match_count as _role_match
    title_matched = [j for j in jobs if _role_match(j.get("title", ""), [role]) > 0]
    print(f"  title-matched: {len(title_matched)} / {len(jobs)}")
    for i, j in enumerate(jobs, 1):
        match = "*" if j in title_matched else " "
        title = (j.get("title") or "")[:60]
        company = (j.get("company") or "")[:30]
        loc = (j.get("location") or "")[:30]
        exp = j.get("experience_level") or ""
        print(f"  {match}{i:>3}. {title:<62} | {company:<32} | {loc:<32} | {exp}")


def main():
    ap = argparse.ArgumentParser(description="Test Indeed/LinkedIn scrapers")
    ap.add_argument("--site", choices=["indeed", "linkedin", "both"], default="both")
    ap.add_argument("--role", action="append", default=[], help="role to search (repeatable)")
    ap.add_argument("--location", default="")
    ap.add_argument("--country", default="USA")
    ap.add_argument("--internship", action="store_true")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--hours", type=int, default=72)
    args = ap.parse_args()

    roles = args.role or ["Software Engineer"]
    sites = ["indeed", "linkedin"] if args.site == "both" else [args.site]

    for role in roles:
        for site in sites:
            kw = dict(
                roles=[role],
                internship_mode=args.internship,
                results_wanted=args.limit,
                hours_old=args.hours,
            )
            if site == "indeed":
                kw["location"] = args.location or "United States"
                kw["country_indeed"] = args.country
            else:
                kw["location"] = args.location or "United States"
            try:
                jobs = scrape_indeed(**kw) if site == "indeed" else scrape_linkedin(**kw)
            except Exception as e:
                print(f"\n=== {site.upper()} FAILED for '{role}': {type(e).__name__}: {e} ===")
                continue
            summarize(site, role, jobs)


if __name__ == "__main__":
    main()

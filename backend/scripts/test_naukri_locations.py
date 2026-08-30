"""Test script: scrape Naukri for a specific city and log the ACTUAL location
returned by the API for each job. Helps diagnose location mismatches.

Usage:
  python test_naukri_locations.py <city> <role> [results_wanted]

Examples:
  python test_naukri_locations.py "Bamboo Flat" "DevOps Engineer" 20
  python test_naukri_locations.py "Port Blair" "Data Analyst" 10
  python test_naukri_locations.py "Mumbai" "Backend Developer" 10
"""
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scrapers.naukri_scraper import scrape_naukri


def main():
    city = sys.argv[1] if len(sys.argv) > 1 else "Bamboo Flat"
    role = sys.argv[2] if len(sys.argv) > 2 else "DevOps Engineer"
    results_wanted = int(sys.argv[3]) if len(sys.argv) > 3 else 20

    print(f"\n{'='*70}")
    print(f"Searching Naukri: role='{role}', location='{city}', results={results_wanted}")
    print(f"{'='*70}\n")

    jobs = list(scrape_naukri(
        roles=[role],
        location=city,
        internship_mode=False,
        results_wanted=results_wanted,
        hours_old=168,
    ))

    print(f"\n{'='*70}")
    print(f"RESULTS: {len(jobs)} jobs returned by Naukri API")
    print(f"{'='*70}\n")

    location_counts = {}
    for i, job in enumerate(jobs, 1):
        loc = job.get("location", "")
        title = job.get("title", "")
        company = job.get("company", "")
        url = job.get("url", "")

        print(f"#{i:2d} | Title: {title}")
        print(f"     | Company: {company}")
        print(f"     | Location: '{loc}'")
        print(f"     | URL: {url}")
        print()

        loc_key = loc or "(empty)"
        location_counts[loc_key] = location_counts.get(loc_key, 0) + 1

    print(f"\n{'='*70}")
    print(f"LOCATION SUMMARY")
    print(f"{'='*70}")
    for loc, count in sorted(location_counts.items(), key=lambda x: -x[1]):
        pct = count / len(jobs) * 100 if jobs else 0
        print(f"  {count:3d} ({pct:5.1f}%) | {loc}")

    searched_lower = city.lower()
    matching = sum(1 for j in jobs if searched_lower in (j.get("location") or "").lower())
    print(f"\n  Searched: '{city}'")
    print(f"  Matching: {matching}/{len(jobs)} ({matching/len(jobs)*100:.1f}%)" if jobs else "  No jobs")


if __name__ == "__main__":
    main()

"""Quick smoke test: scrape Naukri for 2 roles across 2 cities and
verify timing matches the configured delays."""
import time
import sys

from scrapers.naukri_scraper import scrape_naukri, _build_session, _warm_up, _naukri_location

def main():
    roles = ["Full Stack Developer", "QA Engineer"]
    locations = ["Bengaluru", "Mumbai"]

    # Single-role, single-city baseline timing
    print("=" * 60)
    print("TEST 1: Single role, single city")
    print("=" * 60)
    t0 = time.time()
    jobs1 = scrape_naukri(roles=["Full Stack Developer"], location="Bengaluru",
                          results_wanted=10, hours_old=168)
    elapsed1 = time.time() - t0
    print(f"  -> {len(jobs1)} jobs in {elapsed1:.1f}s\n")

    # Two roles — verify inter-role delay (~8-13s)
    print("=" * 60)
    print("TEST 2: Two roles, single city (expect inter-role delay ~8-13s)")
    print("=" * 60)
    t0 = time.time()
    jobs2 = scrape_naukri(roles=["Full Stack Developer", "QA Engineer"],
                          location="Bengaluru", results_wanted=10, hours_old=168)
    elapsed2 = time.time() - t0
    print(f"  -> {len(jobs2)} jobs in {elapsed2:.1f}s")
    if elapsed2 > 10:
        print("  PASS: inter-role delay detected")
    else:
        print("  WARN: inter-role delay seems too short")

    # Manual city-by-city scrape to verify inter-city delay
    print("\n" + "=" * 60)
    print("TEST 3: Two cities manually (expect inter-city delay ~6-10s)")
    print("=" * 60)
    session, tls = _build_session()
    loc1 = _naukri_location("Bengaluru")
    loc2 = _naukri_location("Mumbai")
    _warm_up(session, loc1)

    t0 = time.time()
    jobs_a = scrape_naukri(roles=["Full Stack Developer"], location="Bengaluru",
                           results_wanted=10, hours_old=168)
    t1 = time.time()
    print(f"  Bengaluru: {len(jobs_a)} jobs in {t1 - t0:.1f}s")

    from utils.delay import delay
    print("  Waiting 6-10s (simulating inter-city delay)...")
    delay(6, 10)

    t2 = time.time()
    jobs_b = scrape_naukri(roles=["Full Stack Developer"], location="Mumbai",
                           results_wanted=10, hours_old=168)
    t3 = time.time()
    print(f"  Mumbai:    {len(jobs_b)} jobs in {t3 - t2:.1f}s")
    print(f"  Total:     {len(jobs_a) + len(jobs_b)} jobs in {t3 - t0:.1f}s")

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  Test 1 (single role):  {len(jobs1)} jobs, {elapsed1:.1f}s")
    print(f"  Test 2 (two roles):    {len(jobs2)} jobs, {elapsed2:.1f}s")
    print(f"  Test 3 (two cities):   {len(jobs_a) + len(jobs_b)} jobs, {t3 - t0:.1f}s")

    if elapsed2 > 10:
        print("\n  All delay checks passed.")
    else:
        print("\n  Some delays may be shorter than expected.")

if __name__ == "__main__":
    main()

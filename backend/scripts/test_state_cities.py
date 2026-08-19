"""Validate every CACHE_STATE_CITIES token against live Naukri.

For each (state -> city) mapping, run a real Naukri search for 'Data Analyst'
and record whether jobs come back. Results are written incrementally to
city_map_results.json so a restart resumes where it left off.

Usage:
    python test_state_cities.py [STATE_FILTER] [MAX_TOKENS]
"""
import contextlib
import io
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import config
from scrapers import naukri_scraper as ns

# Our cooldown handles blocked periods; don't double up on the scraper's
# 8-12s 406 retries per token (this script re-tests blocked tokens anyway).
ns.NAUKRI_MAX_406_RETRIES = 0

RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "city_map_results.json")
STATE_FILTER = sys.argv[1] if len(sys.argv) > 1 else None
MAX_TOKENS = int(sys.argv[2]) if len(sys.argv) > 2 else 0

results = {}
if os.path.exists(RESULTS):
    with open(RESULTS, encoding="utf-8") as f:
        results = json.load(f)

# RATE_LIMITED is transient (Naukri recaptcha), so keep re-testing blocked
# tokens until they resolve to FOUND/EMPTY.
FINAL_STATUSES = {"FOUND", "EMPTY"}

total_tokens = sum(len(v) for v in config.CACHE_STATE_CITIES.values())
done = 0
consecutive_rl = 0
for state, cities in config.CACHE_STATE_CITIES.items():
    if STATE_FILTER and state != STATE_FILTER:
        continue
    for city in cities:
        key = f"{state}:::{city}"
        prev = results.get(key)
        if prev and prev.get("status") in FINAL_STATUSES:
            done += 1
            continue
        if MAX_TOKENS and done >= MAX_TOKENS:
            break

        out = {"state": state, "city": city, "status": "ERROR",
               "jobs": 0, "rate_limited": False, "sample": []}
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                jobs = ns.scrape_naukri(roles=["Data Analyst"], location=city,
                                        results_wanted=5, hours_old=168)
            out["jobs"] = len(jobs)
            out["rate_limited"] = "rate-limited (406)" in buf.getvalue()
            out["sample"] = [j.get("location", "")[:40] for j in jobs[:3]]
            if jobs:
                out["status"] = "FOUND"
            elif out["rate_limited"]:
                out["status"] = "RATE_LIMITED"
            else:
                out["status"] = "EMPTY"
        except Exception as e:
            out["status"] = f"ERROR: {e}"

        results[key] = out
        with open(RESULTS, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=1)

        done += 1
        flag = {"FOUND": "+", "EMPTY": "~", "RATE_LIMITED": "!"}.get(out["status"], "?")
        print(f"[{flag}] [{done:4d}/{total_tokens}] {city:24s} <- {state:30s} "
              f"{out['status']} ({out['jobs']} jobs)" + (f"  {out['sample']}" if out["sample"] else ""))
        sys.stdout.flush()

        # Wave strategy: while Naukri 406-blocks us, keep sweeping tokens at
        # fail-fast pace; after a streak of blocks, sleep a fixed long backoff
        # then sweep again. When the block lifts, results flood in.
        if out.get("rate_limited"):
            consecutive_rl += 1
            if consecutive_rl >= 10:
                print(f"    (blocked streak {consecutive_rl}) sleeping 15 min before next sweep...")
                sys.stdout.flush()
                time.sleep(900)
                consecutive_rl = 0
        else:
            consecutive_rl = 0
            time.sleep(3)

from collections import Counter

cnt = Counter(r["status"].split(":")[0] for r in results.values())
print("\n=== SUMMARY ===")
print(f"tokens tested: {len(results)} / {total_tokens}")
for k, v in cnt.most_common():
    print(f"  {k:14s} {v}")
print(f"tokens with jobs: {sum(1 for r in results.values() if r['jobs'] > 0)}")

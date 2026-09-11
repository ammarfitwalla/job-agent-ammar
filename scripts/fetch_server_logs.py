"""Fetch and parse server logs from Oracle instance.

Usage:
    python fetch_server_logs.py              # last 500 lines
    python fetch_server_logs.py --lines 2000 # last 2000 lines
    python fetch_server_logs.py --hours 6    # logs from last 6 hours
"""

import argparse
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime

ORACLE_HOST = "130.210.34.176"
ORACLE_USER = "ubuntu"
SSH_KEY = r"C:\Users\Ammar Fitwalla\.ssh\oracle.key"
CONTAINER = "job-agent"


def ssh_exec(cmd: str, timeout: int = 30) -> str:
    result = subprocess.run(
        ["ssh", "-i", SSH_KEY, "-o", "StrictHostKeyChecking=no", f"{ORACLE_USER}@{ORACLE_HOST}", cmd],
        capture_output=True, text=True, timeout=timeout,
    )
    if result.returncode != 0:
        print(f"SSH error: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)
    return result.stdout


def fetch_logs(lines: int = 500) -> str:
    return ssh_exec(f"sudo docker logs {CONTAINER} --tail {lines} 2>&1")


def parse_logs(raw: str):
    lines = raw.splitlines()

    errors_406 = []
    errors_5xx = []
    jobs_fetched = defaultdict(list)  # scraper -> list of (role, location, count)
    total_fetched = 0
    combo_results = []  # (combo, local_matches, status)

    # Pattern: "POST /scrape/..." or "GET /scrape/..."
    # Pattern: [SCRAPE] BATCH Role @ site: N fetched, M title-matched
    batch_re = re.compile(
        r"\[SCRAPE\]\s+BATCH\s+(.+?)\s*@\s*(\w+)\s*:\s*(\d+)\s*fetched,\s*(\d+)\s*title-matched"
    )
    # Pattern: [SCRAPE] Role @ site — Location: N local matches
    local_re = re.compile(
        r"\[SCRAPE\]\s+(.+?)\s*@\s*(\w+)\s*[—–-]\s*(.+?):\s*(\d+)\s*local matches"
    )
    # Pattern: HTTP 406
    http_406_re = re.compile(r'"(POST|GET)\s+(/\S+)\s+HTTP/\S+"\s+406')
    # Pattern: HTTP 5xx
    http_5xx_re = re.compile(r'"(POST|GET)\s+(/\S+)\s+HTTP/\S+"\s+5\d\d')
    # Pattern: [NAUKRI] 'Role': N new unique jobs
    unique_re = re.compile(r"\[(\w+)\]\s+'(.+?)':\s*(\d+)\s*new unique jobs")
    # Pattern: [SCRAPE] Role @ site — Location: 0 local matches, skipping
    skip_re = re.compile(
        r"\[SCRAPE\]\s+(.+?)\s*@\s*(\w+)\s*[—–-]\s*(.+?):\s*0\s*local matches.*skipping"
    )

    for line in lines:
        # 406 errors
        m = http_406_re.search(line)
        if m:
            errors_406.append({"method": m.group(1), "path": m.group(2), "raw": line.strip()})

        # 5xx errors
        m = http_5xx_re.search(line)
        if m:
            errors_5xx.append({"method": m.group(1), "path": m.group(2), "raw": line.strip()})

        # Batch fetch counts
        m = batch_re.search(line)
        if m:
            role, site, fetched, matched = m.group(1), m.group(2), int(m.group(3)), int(m.group(4))
            jobs_fetched[site].append({"role": role, "fetched": fetched, "title_matched": matched})
            total_fetched += fetched

        # Local matches
        m = local_re.search(line)
        if m:
            role, site, location, count = m.group(1), m.group(2), m.group(3), int(m.group(4))
            combo_results.append({"role": role, "site": site, "location": location, "local_matches": count})

        # Zero local matches (skipped)
        m = skip_re.search(line)
        if m:
            role, site, location = m.group(1), m.group(2), m.group(3)
            combo_results.append({"role": role, "site": site, "location": location, "local_matches": 0})

    return {
        "errors_406": errors_406,
        "errors_5xx": errors_5xx,
        "jobs_fetched": dict(jobs_fetched),
        "total_fetched": total_fetched,
        "combo_results": combo_results,
    }


def print_report(data: dict):
    print("=" * 70)
    print("  SERVER LOG REPORT")
    print("=" * 70)

    # 406 errors
    print(f"\n--- 406 Errors: {len(data['errors_406'])} ---")
    for e in data["errors_406"]:
        print(f"  {e['method']} {e['path']}")
    if not data["errors_406"]:
        print("  (none)")

    # 5xx errors
    print(f"\n--- 5xx Errors: {len(data['errors_5xx'])} ---")
    for e in data["errors_5xx"][:20]:
        print(f"  {e['method']} {e['path']}")
    if len(data["errors_5xx"]) > 20:
        print(f"  ... and {len(data['errors_5xx']) - 20} more")
    if not data["errors_5xx"]:
        print("  (none)")

    # Jobs fetched by site
    print(f"\n--- Jobs Fetched by Site (total: {data['total_fetched']}) ---")
    for site, batches in sorted(data["jobs_fetched"].items()):
        site_total = sum(b["fetched"] for b in batches)
        site_matched = sum(b["title_matched"] for b in batches)
        print(f"  {site}: {site_total} fetched, {site_matched} title-matched ({len(batches)} batches)")
        # Group by role
        by_role = defaultdict(lambda: {"fetched": 0, "matched": 0, "count": 0})
        for b in batches:
            by_role[b["role"]]["fetched"] += b["fetched"]
            by_role[b["role"]]["matched"] += b["title_matched"]
            by_role[b["role"]]["count"] += 1
        for role, stats in sorted(by_role.items()):
            print(f"    {role}: {stats['fetched']} fetched, {stats['matched']} matched ({stats['count']} batches)")

    # Local matches summary
    if data["combo_results"]:
        print(f"\n--- Combo Results: {len(data['combo_results'])} combos ---")
        with_matches = [c for c in data["combo_results"] if c["local_matches"] > 0]
        no_matches = [c for c in data["combo_results"] if c["local_matches"] == 0]
        print(f"  With local matches: {len(with_matches)}")
        print(f"  Zero local matches: {len(no_matches)}")
        if with_matches:
            print("\n  Combos with matches:")
            for c in with_matches:
                print(f"    {c['role']} @ {c['site']} — {c['location']}: {c['local_matches']} jobs")

    print("\n" + "=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Fetch and parse server logs")
    parser.add_argument("--lines", type=int, default=500, help="Number of log lines to fetch (default: 500)")
    args = parser.parse_args()

    print(f"Fetching last {args.lines} lines from {ORACLE_HOST}...")
    raw = fetch_logs(args.lines)
    print(f"Got {len(raw.splitlines())} lines. Parsing...\n")

    data = parse_logs(raw)
    print_report(data)


if __name__ == "__main__":
    main()

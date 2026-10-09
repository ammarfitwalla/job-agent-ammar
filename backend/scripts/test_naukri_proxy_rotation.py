"""Standalone smoke test for Naukri proxy rotation + scraping.

Runs three phases and prints a report:

  1. POOL      - current DB proxy pool stats for the `naukri` board.
  2. ROTATION  - claim N proxies from the pool, probe each against the Naukri
                 search API AND an IP-echo endpoint, so we can see that
                 requests really egress from different IPs.
  3. SCRAPE    - run `scrape_naukri` for several different job roles and report
                 how many jobs each role returned and how long it took.

Usage (run from the `backend/` directory):

    ..\\venv\\Scripts\\python.exe scripts\\test_naukri_proxy_rotation.py
    ..\\venv\\Scripts\\python.exe scripts\\test_naukri_proxy_rotation.py --proxies 8 --roles 4

Exit code is 0 if the scrape produced at least one job, else 1.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

IP_ECHO_URL = "https://api.ipify.org?format=json"

DEFAULT_ROLES = [
    "Full Stack Developer",
    "Data Analyst",
    "QA Engineer",
    "DevOps Engineer",
    "Machine Learning Engineer",
    "Product Manager",
    "Data Scientist",
]
DEFAULT_LOCATION = ""


def _line(char="="):
    print(char * 70)


def phase_pool(board: str = "naukri"):
    print("\n" + "=" * 70)
    print("PHASE 1: proxy pool")
    print("=" * 70)
    import db
    stats = db.proxy_pool_stats(board)
    print(f"  board={stats['board']}  free={stats['free']} "
          f"in_use={stats['in_use']} dead={stats['dead']}")
    return stats


def _outbound_ip(session, tls):
    """Best-effort outbound IP lookup through an already-built session."""
    try:
        if tls:
            r = session.get(IP_ECHO_URL, timeout_seconds=10)
        else:
            r = session.get(IP_ECHO_URL, timeout=10)
        if r is not None and r.status_code == 200:
            import json
            return json.loads(r.text).get("ip")
    except Exception:
        pass
    return None


def phase_rotation(n_proxies):
    """Claim proxies and probe each: Naukri reachability + egress IP."""
    from scrapers.naukri_scraper import _build_session, _proxy_test_naukri, _BOARD
    from db import claim_proxies, release_proxy

    print("\n" + "=" * 60)
    print(f"PHASE 2: ROTATION - probing {n_proxies} proxies")
    print("=" * 60)

    proxies = claim_proxies(_BOARD, n_proxies, lease_minutes=10)
    if not proxies:
        print("  No proxies could be claimed from the pool.")
        return {"claimed": 0, "naukri_ok": 0, "ips": set(), "tested": 0}

    print(f"  claimed {len(proxies)} proxies\n")
    naukri_ok = 0
    tested = 0
    ips = set()
    per_proxy = []
    try:
        for i, p in enumerate(proxies, 1):
            tested += 1
            session, tls = _build_session(p)
            ok = _proxy_test_naukri(p)
            ip = _outbound_ip(session, tls)
            if ok:
                naukri_ok += 1
            if ip:
                ips.add(ip)
            per_proxy.append((p, ok, ip))
            mark = "OK " if ok else "FAIL"
            print(f"  [{i:>2}/{len(proxies)}] {mark} naukri  ip={ip or '-':<16} {p}")
    finally:
        for p in proxies:
            try:
                release_proxy(_BOARD, p)
            except Exception:
                pass

    print(f"\n  reachable on Naukri : {naukri_ok}/{tested}")
    print(f"  distinct egress IPs : {len(ips)}")
    return {"claimed": len(proxies), "naukri_ok": naukri_ok,
            "ips": ips, "tested": tested}


def phase_scrape(roles, location, results_wanted):
    """Run the real scraper across several roles and report per-role results."""
    from scrapers.naukri_scraper import scrape_naukri

    print("\n" + "=" * 60)
    print(f"PHASE 3: SCRAPE - {len(roles)} roles, "
          f"~{results_wanted} results/role, location='{location or 'any'}'")
    print("=" * 60)

    per_role = []
    t_all = time.time()
    for role in roles:
        t0 = time.time()
        jobs = scrape_naukri(roles=[role], location=location,
                             results_wanted=results_wanted, hours_old=168)
        dt = time.time() - t0
        per_role.append((role, len(jobs), dt))
        sample = jobs[0]["title"] if jobs else "-"
        print(f"  {role:<28} {len(jobs):>3} jobs  {dt:>5.1f}s   e.g. {sample}")

    total = sum(n for _, n, _ in per_role)
    print(f"\n  TOTAL: {total} jobs across {len(roles)} roles "
          f"in {time.time() - t_all:.1f}s")
    empty = [r for r, n, _ in per_role if n == 0]
    if empty:
        print(f"  roles with 0 jobs: {', '.join(empty)}")
    return per_role


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--proxies", type=int, default=12,
                    help="how many proxies to probe in the rotation phase")
    ap.add_argument("--results", type=int, default=6,
                    help="results wanted per role in the scrape phase")
    ap.add_argument("--location", default="",
                    help="Naukri location filter (e.g. Bengaluru)")
    ap.add_argument("--roles", nargs="*", default=None,
                    help="override the default role list")
    ap.add_argument("--skip-rotation", action="store_true",
                    help="skip proxy probing, only scrape")
    ap.add_argument("--skip-scrape", action="store_true",
                    help="only probe proxies, do not scrape")
    args = ap.parse_args()

    roles = args.roles or DEFAULT_ROLES

    print("=" * 70)
    print("NAUKRI PROXY ROTATION + SCRAPE SMOKE TEST")
    print("=" * 70)

    phase_pool()

    rotation = None
    if not args.skip_rotation:
        rotation = phase_rotation(args.proxies)

    scrape = None
    if not args.skip_scrape:
        scrape = phase_scrape(roles, args.location, args.results)

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    if rotation:
        print(f"  proxy reachability : {rotation['naukri_ok']}/{rotation['tested']}")
        print(f"  distinct egress IPs: {len(rotation['ips'])} "
              f"(rotation {'WORKS' if len(rotation['ips']) > 1 else 'looks stuck'})")
    if scrape:
        total = sum(n for _, n, _ in scrape)
        print(f"  scraped jobs       : {total}")
        print(f"  scraping           : {'WORKS' if total > 0 else 'RETURNED NOTHING'}")

    if scrape and sum(n for _, n, _ in scrape) == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()

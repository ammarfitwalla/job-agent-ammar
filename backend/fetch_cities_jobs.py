"""Fetch jobs across job boards for a list of cities only (no state/country).

Standalone, runs from the `backend/` directory (imports scrapers + config):

    python fetch_cities_jobs.py --roles "data engineer" "sde" \
        --cities Bengaluru Mumbai Pune --sites naukri,indeed,linkedin

City lists can come from the offline countrystatecity package (no API key):

    python fetch_cities_jobs.py --roles "sde" --cities-from "in:KA,MH us:CA" \
        --cities-limit 10 --sites indeed,linkedin

    python fetch_cities_jobs.py --list-cities "in:KA" --cities-limit 5

Only boards that can take a bare city token are supported: Naukri, Indeed,
LinkedIn. Results are deduped by URL, tagged with the searched city/role, and
written to a single JSON file with a console summary.
"""
import argparse
import json
import time
import types
from datetime import datetime, timezone

from scrapers import naukri_scraper, indeed_scraper, linkedin_scraper

SITES = {
    "naukri": naukri_scraper.scrape_naukri,
    "indeed": indeed_scraper.scrape_indeed,
    "linkedin": linkedin_scraper.scrape_linkedin,
}

_COUNTRY_CODES = {
    "india": "in", "usa": "us", "united states": "us", "united kingdom": "gb",
    "uk": "gb", "canada": "ca", "australia": "au", "germany": "de",
    "france": "fr", "singapore": "sg", "uae": "ae",
    "united arab emirates": "ae", "japan": "jp", "netherlands": "nl",
}


def _resolve_country_code(country: str) -> str:
    return _COUNTRY_CODES.get((country or "").strip().lower(), "")


def _get_city_state_lists(locations):
    """Resolve "CC:S1,S2 DD:F" specs into (city_name, country_code) pairs."""
    from countrystatecity_countries import get_states_of_country, get_cities_of_state

    pairs = []
    if isinstance(locations, str):
        locations = locations.split()
    for spec in locations:
        spec = spec.strip()
        if not spec:
            continue
        cc, _, states = spec.partition(":")
        cc = cc.strip().upper()
        wanted = [s.strip().upper() for s in states.split(",") if s.strip()]
        try:
            sts = get_states_of_country(cc)
        except Exception as e:
            print(f"[SKIP] country {cc}: {e}")
            continue
        if not wanted:
            wanted = [s.state_code for s in sts]
        seen_codes = set()
        for sc in wanted:
            try:
                for s in sts:
                    if s.state_code == sc:
                        seen_codes.add(sc)
                        for c in get_cities_of_state(cc, sc):
                            pairs.append((c.name, cc.lower()))
                        break
            except Exception as e:
                print(f"[SKIP] {cc}:{sc}: {e}")
        missing = [sc for sc in wanted if sc not in seen_codes]
        if missing:
            print(f"[WARN] {cc}: unknown state code(s) {', '.join(missing)} "
                  f"(first known: {sts[0].state_code})")

    # Dedupe city names (React with the larger city/state set
    seen = set()
    unique = []
    for name, cc in pairs:
        k = (name.lower(), cc)
        if k not in seen:
            seen.add(k)
            unique.append((name, cc))
    return unique


def _city_token_validation(cities, country):
    """Warn when a bare --cities token isn't in the package's city list for
    the given country (the source of truth for board-compatible spellings)."""
    cc = _resolve_country_code(country)
    if not cc:
        return
    from countrystatecity_countries import get_states_of_country, get_cities_of_state
    try:
        known = set()
        for s in get_states_of_country(cc):
            known.update(c.name.lower() for c in get_cities_of_state(cc, s.state_code))
    except Exception:
        return
    for city in cities:
        if city.strip().lower() not in known:
            print(f"[WARN] '{city}' not found in {cc} city list "
                  f"(typo? or wrong --country '{country}'?)")


def _read_cities_file(path):
    cities = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    cities.append(line)
    except OSError as e:
        print(f"[ERROR] cannot read --cities-file {path}: {e}")
    return cities


def _collect(result):
    """Flatten a scraper result into a list of jobs.

    LinkedIn yields batches (generator); Naukri/Indeed return a static list.
    """
    jobs = []
    if isinstance(result, types.GeneratorType):
        for batch in result:
            if batch:
                jobs.extend(batch)
    elif result:
        jobs.extend(result)
    return jobs


def _tag(job, site, role, city):
    job["searched_city"] = city
    job["searched_role"] = role
    job["site"] = site
    return job


def main():
    parser = argparse.ArgumentParser(description="Fetch jobs for cities across city-capable job boards.")
    parser.add_argument("--roles", nargs="+", help="Role/term to search, e.g. \"data engineer\" \"sde\" (required unless --list-cities)")
    parser.add_argument("--cities", nargs="+", help="City names (bare, exact Naukri tokens), e.g. Bengaluru Mumbai Pune")
    parser.add_argument("--cities-from", help="Resolve cities from the countrystatecity package, e.g. \"in:KA,MH us:CA\" (states optional)")
    parser.add_argument("--cities-file", help="Read city names from a file, one per line")
    parser.add_argument("--cities-limit", type=int, default=0, help="Cap the number of cities (from --cities-from) to this many")
    parser.add_argument("--list-cities", nargs="?", const="", metavar="LOCS", help="Print resolved city names (one per line) and exit. LOCS = --cities-from style specs; if omitted, prints --cities/--cities-from/--cities-file result")
    parser.add_argument("--sites", default="naukri,indeed,linkedin", help="Comma list of city-capable sites")
    parser.add_argument("--results", type=int, default=20, help="Per-role/city/site target count")
    parser.add_argument("--hours", type=int, default=72, help="Hours-old cutoff for freshness")
    parser.add_argument("--internship", action="store_true", help="Restrict to internship-level results")
    parser.add_argument("--country", default="India", help="Country hint for Indeed's domain and --cities validation (city token itself stays bare)")
    parser.add_argument("--out", default="", help="Output JSON path (default: fetch_cities_<UTC timestamp>.json in cwd)")
    parser.add_argument("--verbose", action="store_true", help="Log each role/city/site call")
    args = parser.parse_args()

    sites = [s.strip().lower() for s in args.sites.split(",") if s.strip()]
    unknown = [s for s in sites if s not in SITES]
    if unknown:
        print(f"[ERROR] Unsupported site(s): {', '.join(unknown)} (city-capable: {', '.join(SITES)})")
        return

    cities = list(args.cities or [])
    if args.cities_file:
        cities += _read_cities_file(args.cities_file)
    if args.cities_from:
        resolved = _get_city_state_lists(args.cities_from.split())
        cities += [name for name, _ in resolved]
        if not resolved:
            print("[ERROR] --cities-from resolved to no cities")
            return
    if args.list_cities is not None:
        if args.list_cities.strip():
            extras = _get_city_state_lists(args.list_cities.split())
            cities = [name for name, _ in extras] or cities
        if not cities:
            print("[ERROR] nothing to list - provide --cities, --cities-from, or --list-cities LOCS")
            return
        if args.cities_limit > 0:
            cities = cities[: args.cities_limit]
        for c in cities:
            print(c)
        return
    if args.cities_limit > 0:
        cities = cities[: args.cities_limit]
    if not cities:
        print("[ERROR] provide --cities, --cities-from, and/or --cities-file")
        return
    if not args.roles:
        print("[ERROR] provide --roles, e.g. --roles \"data engineer\"")
        return

    if args.cities or args.cities_file:
        _city_token_validation(cities, args.country)

    run_start = time.time()
    all_jobs = []
    seen_urls = set()
    failures = {}

    try:
        for role in args.roles:
            for city in cities:
                for site in sites:
                    try:
                        if args.verbose:
                            print(f"[FETCH] {role} @ {site} - {city}")
                        scraper_fn = SITES[site]
                        kwargs = {
                            "roles": [role],
                            "location": city,
                            "results_wanted": args.results,
                            "internship_mode": args.internship,
                            "hours_old": args.hours,
                        }
                        if site == "linkedin":
                            kwargs["fetch_descriptions"] = False
                        if site == "indeed":
                            kwargs["country_indeed"] = args.country
                        result = scraper_fn(**kwargs)
                        jobs = _collect(result)

                        added = 0
                        for j in jobs:
                            url = j.get("url", "")
                            if url:
                                if url in seen_urls:
                                    continue
                                seen_urls.add(url)
                            all_jobs.append(_tag(j, site, role, city))
                            added += 1
                        if args.verbose:
                            print(f"[FETCH] {role} @ {site} - {city}: {added} kept ({len(jobs)} fetched)")
                    except Exception as e:
                        failures.setdefault(site, []).append(f"{role} / {city}: {e}")
                        print(f"[ERROR] {role} @ {site} - {city}: {e}")
    except KeyboardInterrupt:
        print("\n[STOP] Interrupted (results so far will still be written).")

    elapsed = round(time.time() - run_start, 1)

    out = args.out or f"fetch_cities_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump({
            "meta": {
                "run_at_utc": datetime.now(timezone.utc).isoformat(),
                "roles": args.roles,
                "cities": cities,
                "sites": sites,
                "results_wanted": args.results,
                "hours_old": args.hours,
                "internship": args.internship,
                "country": args.country,
                "total_jobs": len(all_jobs),
                "elapsed_seconds": elapsed,
                "failures": failures,
            },
            "jobs": all_jobs,
        }, f, ensure_ascii=False, indent=2)

    print("=" * 60)
    print(f"TOTAL {len(all_jobs)} unique jobs  ({elapsed}s) -> {out}")
    site_counts = {}
    city_counts = {}
    for j in all_jobs:
        site_counts[j["site"]] = site_counts.get(j["site"], 0) + 1
        city_counts[j["searched_city"]] = city_counts.get(j["searched_city"], 0) + 1
    print("Per site:")
    for site in sites:
        print(f"  {site:<10} {site_counts.get(site, 0)}")
    print("Per city:")
    for city in cities:
        print(f"  {city:<20} {city_counts.get(city, 0)}")
    if failures:
        print("Failures:")
        for site, errs in failures.items():
            print(f"  {site}: {len(errs)} combo(s) failed (first: {errs[0]})")


if __name__ == "__main__":
    main()
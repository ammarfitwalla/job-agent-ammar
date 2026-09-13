"""Smoke test: verify the offline countrystatecity package returns city names
for a matrix of countries and states. No API key, no network.

Run from `backend/`:

    python test_cities_api.py
    python test_cities_api.py --countries=IN,US
    python test_cities_api.py --states="IN:KA,MH" "US:CA,TX"

Exits non-zero if any queried state returns no cities or errors.
"""
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    from countrystatecity_countries import get_states_of_country, get_cities_of_state
except ImportError as e:
    print(f"[ERROR] countrystatecity-countries not installed: {e}")
    print("        pip install --upgrade countrystatecity-countries")
    sys.exit(1)


DEFAULT_MATRIX = {
    "IN": ["KA", "MH", "DL", "TN"],
    "US": ["CA", "TX", "NY"],
    "GB": ["OXF", "EDH", "SWA"],
    "DE": ["BY", "BE", "HE"],
    "CA": ["ON", "BC", "QC"],
    "AU": ["NSW", "VIC", "WA"],
    "AE": ["DU", "AZ"],
    "FR": ["IDF", "ARA", "OCC"],
    "SG": [],  # city-state: no states expected
    "JP": ["13", "27", "40"],  # Tokyo, Osaka, Fukuoka
}


def _parse_args(argv):
    countries = []
    explicit = {}
    for a in argv:
        if a.startswith("--countries="):
            countries = [p.strip().upper() for p in a.split("=", 1)[1].split(",") if p.strip()]
    for a in argv:
        if a.startswith("--states="):
            for part in a.split("=", 1)[1].split():
                if ":" in part:
                    cc, s = part.split(":", 1)
                    explicit[cc.strip().upper()] = [x.strip().upper() for x in s.split(",") if x.strip()]
    if countries:
        return {c: explicit.get(c, []) for c in countries}
    if explicit:
        return explicit
    return dict(DEFAULT_MATRIX)


def main():
    matrix = _parse_args(sys.argv[1:])
    total_cities = 0
    states_checked = 0
    failures = 0

    print("=" * 72)
    print("CITIES API CHECK (offline countrystatecity-countries, no API key)")
    print("=" * 72)

    for cc, wanted in matrix.items():
        try:
            states = get_states_of_country(cc)
        except Exception as e:
            failures += 1
            print(f"\n[{cc}] ERROR fetching states: {e}")
            continue

        if not wanted:
            wanted = [s.state_code for s in states[:3]]
        elif wanted == ["__all__"]:
            wanted = [s.state_code for s in states]

        print(f"\n--- {cc} ({len(states)} states) ---")
        for sc in wanted:
            try:
                cities = get_cities_of_state(cc, sc)
            except Exception as e:
                failures += 1
                print(f"  {sc:<6} ERROR: {e}")
                continue
            names = [c.name for c in cities]
            states_checked += 1
            total_cities += len(names)
            if not names:
                failures += 1
                print(f"  {sc:<6}     0 cities  <-- EMPTY")
            else:
                sample = ", ".join(names[:4])
                print(f"  {sc:<6} {len(names):>5} cities  e.g. {sample}")

    print("=" * 72)
    print(f"TOTAL {total_cities} cities from {states_checked} state queries")
    if failures:
        print(f"FAILED: {failures} check(s) failed")
        return 1
    print("PASS: cities returned for every country/state")
    return 0


if __name__ == "__main__":
    sys.exit(main())
from fastapi import APIRouter
import time
from countrystatecity_countries import get_countries, get_states_of_country, get_cities_of_state
from api.routes.states import COMMON_COUNTRIES

router = APIRouter(prefix="/cities", tags=["cities"])

_country_map = {}
_cities_cache = {}
_cities_ok = {}
_cache_timestamp = 0
_CACHE_TTL = 60 * 60 * 24
_GLOBAL_SEARCH_LIMIT = 12


def _country_names():
    global _country_map
    if not _country_map:
        try:
            for c in get_countries():
                _country_map[c.iso2.lower()] = c.name
        except Exception:
            _country_map = {}
    return _country_map


def _city_plan(cc: str):
    """Build list of (state_name, [city names sorted]) for a country code."""
    try:
        states = get_states_of_country(cc)
    except Exception:
        return None, []
    state_name_by_code = {}
    for s in states:
        state_name_by_code[s.state_code.lower()] = s.name
    by_state = {}
    for s in states:
        try:
            cities = get_cities_of_state(cc, s.state_code)
        except Exception:
            cities = []
        names = sorted({c.name for c in cities})
        by_state[s.name] = names
    return state_name_by_code, by_state


def _get_plan(cc: str):
    """Cached {states, codes} plan for a country, or None."""
    global _cache_timestamp
    now = time.time()
    plan = _cities_cache.get(cc)
    if plan and (now - _cache_timestamp) < _CACHE_TTL:
        _cities_ok[cc] = True
        return plan
    state_name_by_code, by_state = _city_plan(cc)
    if by_state:
        plan = {"states": by_state, "codes": state_name_by_code}
        _cities_cache[cc] = plan
        _cities_ok[cc] = True
        _cache_timestamp = now
        return plan
    _cities_ok[cc] = False
    return None


def _filter_plan(cc: str, state_filter: str, qf: str, limit=0):
    """Slice a country plan to matching cities; limit<=0 means unlimited."""
    plan = _get_plan(cc)
    if not plan:
        return []
    codes = plan.get("codes", {})
    country_name = _country_names().get(cc, cc.upper())

    if state_filter:
        candidates = {}
        for sname, cities in plan["states"].items():
            if (sname.lower() == state_filter
                    or (codes.get(state_filter) and codes[state_filter].lower() == sname.lower())):
                candidates[sname] = cities
        if not candidates:
            for sname, cities in plan["states"].items():
                if sname.lower().startswith(state_filter):
                    candidates[sname] = cities
    else:
        candidates = plan["states"]

    result = []
    for sname, cities in candidates.items():
        for city in cities:
            if qf and not city.lower().startswith(qf):
                continue
            result.append({
                "city": city,
                "state": sname,
                "country": country_name,
                "country_code": cc,
            })
            if limit and len(result) >= limit:
                return result
    return result


@router.get("")
async def get_cities(country: str = "", state: str = "", q: str = ""):
    cc = (country or "").strip().lower()
    qf = (q or "").strip().lower()

    if not cc:
        if not qf:
            return {"cities": [], "cached": False}
        # Global search: prefix-match cities across all common countries so a
        # bare city typed with no country hint still suggests results.
        result = []
        for ccode in COMMON_COUNTRIES:
            result.extend(_filter_plan(ccode, "", qf, limit=0))
            if len(result) >= _GLOBAL_SEARCH_LIMIT:
                break
        return {"cities": result[:_GLOBAL_SEARCH_LIMIT], "cached": True}

    state_filter = (state or "").strip().lower()
    return {"cities": _filter_plan(cc, state_filter, qf), "cached": bool(_get_plan(cc))}
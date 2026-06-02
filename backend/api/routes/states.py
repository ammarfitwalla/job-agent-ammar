from fastapi import APIRouter
import time
from countrystatecity_countries import get_countries, get_states_of_country

router = APIRouter(prefix="/states", tags=["states"])

COMMON_COUNTRIES = [
    "us", "gb", "ca", "au", "in", "ae", "de", "fr", "sg", "nl",
    "se", "no", "ch", "it", "es", "nz", "jp", "cn", "br",
    "mx", "za", "sa", "my", "hk", "kr", "dk", "fi", "be", "at",
    "pl", "pt", "lu", "il", "tr", "th", "vn", "ph", "id",
]

_states_cache = []
_cache_timestamp = 0


@router.get("")
async def get_states():
    global _states_cache, _cache_timestamp
    now = time.time()
    if _states_cache:
        return {"states": _states_cache, "cached": True}

    try:
        countries = get_countries()
        country_map = {c.iso2.lower(): c.name for c in countries}
    except Exception:
        if _states_cache:
            return {"states": _states_cache, "cached": True}
        return {"states": [], "cached": False}

    result = []
    for cc in COMMON_COUNTRIES:
        try:
            states = get_states_of_country(cc)
            country_name = country_map.get(cc, cc.upper())
            for s in states:
                result.append({
                    "state": s.name,
                    "country": country_name,
                    "country_code": cc,
                })
        except Exception:
            pass

    _states_cache = result
    _cache_timestamp = now
    return {"states": _states_cache, "cached": False}

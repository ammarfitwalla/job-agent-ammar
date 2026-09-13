# Plan: City in location search (#3)

## Goal
Let users search jobs by **city**, **state**, or **country** — the backend passes the right token to each job board depending on which of the three the user picked. Type-ahead suggestions include city matches (`Bengaluru, Karnataka, India`), and the picked location flows through the request → cache key → scraper payload correctly.

This is separate from `docs/planning/user_location_plan.md` (#9), which covers the *profile-page* location fields.

## Decisions (from user Q&A)
- Cities come from the **offline `countrystatecity-countries` package** (`get_cities_of_state(country_code, state_code)`) — **no API key, no network**, same source as `/states` (`states.py:3`). The live `api.countrystatecity.in` REST API (key already embedded in `search.js:1342`) stays browser-only for the countries autocomplete.
- Backend decides what each board receives: Naukri = bare city/state token; Indeed = `City, State, Country`; LinkedIn = `City, State`. All three accept a bare city (verified live on Indeed/LinkedIn; Naukri is city-native).
- New `/cities` endpoint is **country-scoped** (no global dump — 37 countries ≈ 10MB+).
- Bump `countrystatecity-countries` 1.0.2 → **1.0.5** (171,938 cities, fresher data; `get_cities_of_state` exists in both).

## Already done (2026-09-12, verification tooling)
- `backend/test_cities_api.py` — country/state matrix smoke test (offline, no key). PASS on IN/US/GB/DE/CA/AU/AE/FR/SG/JP (13,049 cities). States checked: GB uses council-area codes (`OXF`/`EDH`/`SWA`, no `ENG`), Telangana = `TG` not `TS`.
- `backend/fetch_cities_jobs.py` gained `--cities-from`/`--cities-file`/`--list-cities`/`--cities-limit` (resolve from the package) + `--cities` token validation against the package.

## Change list

### Backend — cities API
1. **New `backend/api/routes/cities.py`** (mirror `states.py`):
   - `GET /cities?country=in&state=KA` → `get_cities_of_state("in","KA")` → `{cities:[{city,state,country,country_code}], cached}`
   - `GET /cities?country=in` (no state) → aggregate all states' cities of that country
   - `&q=` optional prefix filter; `country` required (empty → `{"cities": []}`)
   - Reuses `COMMON_COUNTRIES` from `api.routes.states`; module-level cache + timestamp like `states.py:14`.
2. **`backend/api/main.py`** — import `cities` (line 13), `app.include_router(cities.router)` after `states.router` (line 210); add `/cities` to `_PUBLIC_NON_API` (line 113) so it stays public like `/states`.

### Backend — free-text city recognition
3. **`backend/api/routes/scrape.py` `_resolve_request_location` (`:777-848`)** — add a `_CITY_INDEX` (mirror of `_STATE_INDEX`, `:785-799`): `{lowercase_city: (city, state_name, country_code)}` built from `get_cities_of_state` over `COMMON_COUNTRIES`. Then:
   - If text matches a city (exact or prefix, city wins over state match when both hit), set `req.city`, `req.state`, `req.country` and compose `req.location = f"{city}, {state}, {country}"`.
   - Goal: a typed city lands in the right cache cell `(city,state,country)` instead of the blank/national `(city="",state="",country="")` cell (today it pollutes the national cache key — `_cache_key` db.py:510).
4. **Per-board token formatters** where runs are built (`:185-207`, `runs = [{"location": ...`]):
   - Replace single `combo.get("location")` with a small `_board_location(site, city, state, country)`:
     - Naukri → `city || state || country` (bare — `_naukri_location` naukri_scraper.py:141 already takes the first segment)
     - Indeed → `[city, state, country].join(", ")` (its `l=` query does best with full form)
     - LinkedIn → `[city, state].join(", ")` (search + substring filter)
   - Keep Naukri's per-city state loop (`:187-195`) untouched; it still passes city-level runs with `results_wanted` capped.
5. **Country-code normalization quirk** — frontend sends `country: loc.country_code` (search.js:1603) while `_resolve_request_location` sometimes sets `req.country` to a name (`:845`). Normalize: keep `req.country` as the ISO2 code end-to-end (cache key uses the literal field); `req.location` carries the display label. Note: `country_indeed` for Indeed comes from `getIndeedCountry(loc)` client-side (`search.js:1487-1492`).

### Frontend — search page city tier (#3)
6. **`frontend/js/search.js`**:
   - `loadStates`/new `loadCities` (`:1351-1357`): keep `/states`; add `GET /cities?country=<cc>` loaded lazily per selected country (or `/cities?country=in&q=` prefix search on typing).
   - Match builder `searchState` (`:1387-1411`): add a **city tier** (`count` window like states) when `allCities` for a country is loaded; label `"City, State, Country"` (`:1407` format).
   - `selectLocation` (`:1429-1448`): carry `city` in the selected object; label unchanged display; clear like today.
   - `getLocation` (`:1493-1497`): compose `[city, state, country]` when city present, fall back to today's `[state, country]`.
   - `resolveLocation` (`:1450-1467`): add city exact-match over `allCities` (so free-text city on blur/`updateNaukriEligibility` still resolves).
   - Naukri eligibility (`:1469-1485`) unchanged (country-gated `in`).
7. **`frontend/index.html:261`** — placeholder → `"City, State or Country"`.

### Cache semantics (no code change expected)
8. City searches create distinct cells `(city,state,country)`; `get_cached_jobs` specificity fallback (`db.py:597-598`) already serves state/country cache when a city cell is cold. Prewarm Naukri per-city expansion (`scheduler.py:64-77`) is city-keyed already. Optional later: extend prewarm-city lists beyond `CACHE_STATE_CITIES` from the package cities so more Indian cities have warm cells.

## Tests & verification
9. `backend/tests/test_integration.py` — `TestCitySearch` (mirror `TestUserLocation` style):
   - `/cities?country=in&state=KA` returns city entries incl. `Bengaluru`; missing `country` → `{cities: []}`.
   - `trigger_scrape` with `req.location="Bengaluru"` (no structured fields) resolves `city`/`state`/`country` and stores the cache entry **under the city key**, not the national one.
   - `_board_location` unit: Naukri→`Bengaluru`, Indeed→`Bengaluru, Karnataka, India`, LinkedIn→`Bengaluru, Karnataka`.
10. Full suite + `py_compile` (touched py) + `node --check frontend/js/search.js`.
11. Manual: type "Bengalur" → city suggestion; pick it → payload contains `city`; run a city with a cold cache → state-level fallback shown; Naukri still token-exact (variant spellings like `Bangalore` warned).
12. Live: `python test_cities_api.py` still PASS; `python fetch_cities_jobs.py --list-cities "in:KA in:MH" --cities-limit 4` still prints.

## Deploy
- Only commit/push/deploy when the user explicitly asks.
- Prod needs: `docker cp` `cities.py`, edit `main.py` in place, `pip install --upgrade countrystatecity-countries` inside the container (or rebuild image), restart, verify `/cities?country=in&state=KA` → ~242 rows.

## Relevant files
- `backend/api/routes/states.py` — template for `cities.py` (`:3`, `:14`, `:19-49`)
- `backend/api/main.py` — router import `:13`, include `:210`, `_PUBLIC_NON_API` `:113`
- `backend/api/routes/scrape.py` — `_STATE_INDEX` `:785-799`, `_resolve_request_location` `:777-848`, runs build `:182-215` (`_board_location`), combos/cache `:591-732`
- `backend/scheduler.py:301` — `location = city or state or country` precedence (keep, used for prewarm)
- `backend/api/schemas.py:36-38` — `city`/`state`/`country` fields (already present)
- `backend/db.py` — `_cache_key:510`, specificity fallback `:597-598`
- `frontend/js/search.js` — location block `:1338-1497`, payload `:1600-1605`
- `frontend/index.html:261` — location placeholder
- `backend/test_cities_api.py`, `backend/fetch_cities_jobs.py` — city-source verification tooling (done)
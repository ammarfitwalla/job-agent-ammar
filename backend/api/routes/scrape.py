import os
import threading
import types
from typing import Optional
from datetime import datetime, timedelta
from fastapi import APIRouter, Query
from api.schemas import ScrapeRequest
from utils.logger import log
from db import create_session, update_session, get_session, set_raw_jobs, get_events, _get_conn

router = APIRouter(prefix="/scrape", tags=["scrape"])

_STALE_TIMEOUT_MINUTES = 15


def cancel_stale_sessions():
    from db import _get_conn
    cutoff = (datetime.utcnow() - timedelta(minutes=_STALE_TIMEOUT_MINUTES)).isoformat()
    try:
        with _get_conn() as (conn, cur):
            cur.execute("SELECT id FROM sessions WHERE status = 'running' AND updated_at < ?", (cutoff,))
            stale = [row[0] for row in cur.fetchall()]
        for sid in stale:
            log(f"[GC] Cancelling stale session {sid}", sid)
            try:
                update_session(sid, cancel=True, status="done")
            except Exception as inner:
                log(f"[GC] Failed to cancel {sid}: {inner}")
    except Exception as e:
        log(f"[GC] Error cancelling stale sessions: {e}")


def _start_stale_cleanup():
    def _loop():
        while True:
            threading.Event().wait(60)
            cancel_stale_sessions()
    t = threading.Thread(target=_loop, daemon=True)
    t.start()


_start_stale_cleanup()


def _save_elapsed(sid):
    s = get_session(sid)
    if s and s.get("created_at"):
        elapsed = (datetime.utcnow() - datetime.fromisoformat(s["created_at"])).total_seconds()
        update_session(sid, elapsed_seconds=round(elapsed, 1))


def _harvest_companies(jobs: list):
    from config import COMPANIES
    from db import batch_add_custom_companies

    seen = set()
    companies = []
    for job in jobs:
        company = job.get("company", "").strip()
        if company and company not in seen:
            seen.add(company)
            if company not in COMPANIES:
                companies.append(company)
    if companies:
        batch_add_custom_companies(companies)


SITE_MAP = {
    "indeed": ("indeed_scraper", "scrape_indeed"),
    "linkedin": ("linkedin_scraper", "scrape_linkedin"),
    "naukri": ("naukri_scraper", "scrape_naukri"),
}


def _is_cancelled(sid: str) -> bool:
    s = get_session(sid)
    return bool(s and s.get("cancel"))


def _resumes_dir() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "resumes")


def _save_resume_text(sid: str, resume_text: str):
    text = (resume_text or "").strip()
    if not text:
        return
    os.makedirs(_resumes_dir(), exist_ok=True)
    with open(os.path.join(_resumes_dir(), f"{sid}.txt"), "w", encoding="utf-8") as f:
        f.write(text)


def _score_jobs(jobs: list, keywords=None):
    """Fill keyword_score for any jobs missing it and sort best-first."""
    from match_engine.relevance_engine import keyword_score as _kw_score
    keywords = keywords or []
    for j in jobs:
        if "keyword_score" not in j or not isinstance(j["keyword_score"], int):
            j["keyword_score"] = _kw_score(
                j.get("title", ""),
                j.get("description", ""),
                j.get("tags", []),
                keywords=keywords,
            )
    jobs.sort(key=lambda j: j.get("keyword_score", 0), reverse=True)


def _scrape_combos(sid, combos, keywords=None, internship_mode=False, hours_old=168,
                   scrape_limit=200, initial_jobs=None, seen_urls=None, on_batch=None,
                   stagger=(1, 3)):
    """Scrape each (role x site) combo: title-match, enrich, filter by experience
    level, dedup, keyword-score, store raw jobs and cache entries incrementally.

    Each combo is a dict with: role, site, location, indeed_country,
    city, state, country, results_wanted (optional). Returns (all_jobs, seen_urls).

    sid may be None for background prewarm (skips session writes/cancel checks);
    stagger is the (min, max) sleep between combos."""
    import importlib
    from match_engine.relevance_engine import role_match_count as _role_match
    from utils.delay import delay as _delay
    from utils.experience_level import detect_experience_level, level_from_job_level

    all_jobs = list(initial_jobs or [])
    seen = set(seen_urls or [])
    combo_index = 0
    total_combos = len(combos)

    for combo in combos:
        combo_index += 1
        role = combo["role"]
        site_key = combo["site"]
        if sid and _is_cancelled(sid):
            log(f"[SCRAPE] Cancelled by user", sid)
            set_raw_jobs(sid, all_jobs)
            _save_elapsed(sid)
            update_session(sid, status="done")
            return all_jobs, seen

        module_name, func_name = SITE_MAP.get(site_key, (None, None))
        if not module_name:
            log(f"[SCRAPE] Unknown site: {site_key}", sid)
            continue

        log(f"[SCRAPE] {role} @ {site_key} ({combo_index}/{total_combos})...", sid)
        combo_jobs = []
        try:
            mod = importlib.import_module(f"scrapers.{module_name}")
            scraper_fn = getattr(mod, func_name)
        except Exception as e:
            log(f"[SCRAPE] {site_key} failed to load: {e}", sid)
            continue

        # Naukri matches by city token, not state name, so a state-level combo
        # loops the state's major cities and merges everything under the state key.
        default_loc = "India" if site_key == "naukri" else "United States"
        runs = [{"location": combo.get("location") or default_loc,
                 "results_wanted": combo.get("results_wanted") or scrape_limit}]
        if site_key == "naukri" and not combo.get("city") and combo.get("state"):
            cities = _state_cities(combo.get("state", ""), combo.get("country", ""))
            if cities:
                from config import (CACHE_CITIES_PER_STATE, CACHE_CITY_RESULTS_WANTED,
                                    CACHE_CITY_INCLUDE_STATE_TERM)
                runs = [{"location": c, "results_wanted": min(scrape_limit, CACHE_CITY_RESULTS_WANTED)}
                        for c in cities[:CACHE_CITIES_PER_STATE]]
                if CACHE_CITY_INCLUDE_STATE_TERM:
                    runs.append({"location": combo.get("state"),
                                 "results_wanted": combo.get("results_wanted") or scrape_limit})

        for run_i, run in enumerate(runs, 1):
            if sid and _is_cancelled(sid):
                break
            log(f"[SCRAPE] {role} @ {site_key} — {run['location']} ({run_i}/{len(runs)})...", sid)
            try:
                kwargs = {"roles": [role], "location": run["location"],
                          "results_wanted": run["results_wanted"],
                          "internship_mode": internship_mode, "hours_old": hours_old}
                if site_key == "linkedin":
                    kwargs["fetch_descriptions"] = False
                if site_key == "indeed":
                    kwargs["country_indeed"] = combo.get("indeed_country", "USA")
                # Execute scraper
                scrape_result = scraper_fn(**kwargs)
            except TypeError:
                try:
                    scrape_result = scraper_fn()
                except Exception as e:
                    log(f"[SCRAPE] {site_key} failed: {e}", sid)
                    continue
            except Exception as e:
                log(f"[SCRAPE] {site_key} failed: {e}", sid)
                continue

            # Check if scraper returned a generator (streaming) or a static list
            if isinstance(scrape_result, types.GeneratorType):
                batch_iterator = scrape_result
            else:
                batch_iterator = [scrape_result]

            # Process jobs in streaming batches
            for jobs_batch in batch_iterator:
                if sid and _is_cancelled(sid):
                    log(f"[SCRAPE] Cancelled by user mid-scrape", sid)
                    break

                if not jobs_batch:
                    continue

                # Title-filter by this role and tag matching jobs
                filtered = []
                for j in jobs_batch:
                    if _role_match(j.get("title", ""), [role]) > 0:
                        j["_matched_role"] = role
                        j["_cache_site"] = site_key
                        j["job_board"] = site_key
                        j["searched_city"] = run["location"]
                        filtered.append(j)

                log(f"[SCRAPE] BATCH {role} @ {site_key}: {len(jobs_batch)} fetched, {len(filtered)} title-matched", sid)

                if not filtered:
                    continue

                # Fetch descriptions only for title-matched jobs
                if site_key == "linkedin":
                    from scrapers.linkedin_scraper import enrich_descriptions as _enrich
                    _enrich(filtered)

                # Experience level detection
                for j in filtered:
                    j["experience_level"] = (
                        detect_experience_level(j.get("title", ""), j.get("description", ""))
                        or level_from_job_level(j.get("job_level"))
                    )

                # In internship mode, drop non-entry-level for this combo
                if internship_mode:
                    before = len(filtered)
                    filtered = [j for j in filtered if j.get("experience_level") in ("internship", "entry_level")]
                    dropped = before - len(filtered)
                    if dropped:
                        log(f"[SCRAPE] BATCH {role} @ {site_key}: internship filter dropped {dropped}", sid)

                # In normal mode, drop intern and entry-level jobs
                if not internship_mode:
                    before = len(filtered)
                    filtered = [j for j in filtered if j.get("experience_level") not in ("internship", "entry_level")]
                    dropped = before - len(filtered)
                    if dropped:
                        log(f"[SCRAPE] BATCH {role} @ {site_key}: normal filter dropped {dropped} intern/entry-level", sid)

                if not filtered:
                    continue

                # Discard nationwide fallback from unrecognized tokens.
                # Applies whenever a state is set (prewarm + live with location).
                # No state = worldwide results (no filter).
                if site_key == "naukri" and combo.get("state"):
                    city_name = run["location"].lower()
                    local = [j for j in filtered if city_name in j.get("location", "").lower()]
                    if local:
                        filtered = local
                    else:
                        log(f"[SCRAPE] {role} @ {site_key} — {run['location']}: "
                            f"0 local matches, skipping (nationwide fallback)", sid)
                        continue

                combo_jobs.extend(filtered)

                # Dedup against accumulated jobs
                new_count = 0
                for j in filtered:
                    key = j.get("url", "") or f"{j.get('title', '')}|{j.get('company', '')}"
                    if key not in seen:
                        seen.add(key)
                        all_jobs.append(j)
                        new_count += 1

                log(f"[SCRAPE] BATCH {role} @ {site_key}: {new_count} new after dedup", sid)

                if new_count == 0:
                    continue

                # Keyword-score all accumulated jobs
                _score_jobs(all_jobs, keywords)

                # Write partial results — frontend picks these up dynamically
                if sid:
                    set_raw_jobs(sid, all_jobs)
                    log(f"[SCRAPE] {role} @ {site_key}: {len(all_jobs)} total jobs stored so far", sid)

                if on_batch:
                    try:
                        on_batch(combo, filtered)
                    except Exception:
                        pass

            # Pause between city runs to avoid Naukri rate-limiting
            if site_key == "naukri" and run_i < len(runs):
                log(f"[SCRAPE] {role} @ {site_key} — pausing 60s before next city...", sid)
                _delay(60, 60)

        # Persist this combo's full snapshot to the job cache (pre-dedup,
        # post-filter). keep_larger preserves richer entries from live searches.
        if combo_jobs:
            from config import CACHE_MAX_JOBS_PER_ENTRY
            from db import save_cache_entry, touch_prewarm_combo
            try:
                save_cache_entry(
                    role, site_key,
                    combo.get("city", ""), combo.get("state", ""), combo.get("country", ""),
                    internship_mode, hours_old, combo_jobs,
                    max_jobs=CACHE_MAX_JOBS_PER_ENTRY, keep_larger=True,
                )
                touch_prewarm_combo(
                    role, site_key,
                    combo.get("city", ""), combo.get("state", ""), combo.get("country", ""),
                    internship_mode, hours_old,
                )
            except Exception as e:
                log(f"[SCRAPE] Cache write failed {role}@{site_key}: {e}", sid)

        # Staggered delay before next site/role combo
        _delay(*stagger)

    return all_jobs, seen


def run_scrape(sid, sites, roles, location, indeed_country,
               keywords=None, internship_mode=False, user_email="", resume_filename="", resume_text="",
               scrape_limit=200, hours_old=168, city="", state="", country="",
               combos=None, initial_jobs=None):
    from db import set_raw_jobs as _set_raw

    create_session(sid, sites=sites, keywords=keywords or [], roles=roles or [], user_email=user_email,
                   location=location or "", internship_mode=internship_mode)
    from db import get_user as _get_user
    session_resume = resume_filename or ""
    if not session_resume and user_email:
        u = _get_user(user_email)
        session_resume = (u or {}).get("resume_filename") or ""
    update_session(sid, status="running", cancel=False, resume_filename=session_resume)
    _save_resume_text(sid, resume_text)

    if combos is None:
        combos = [
            {"role": role, "site": site_key, "location": location or "", "indeed_country": indeed_country,
             "city": city, "state": state, "country": country}
            for role in roles for site_key in sites
        ]

    # Seed the session with cache-served jobs (stale/fresh hits) so results
    # appear instantly while the remaining combos scrape in the background.
    all_jobs = []
    seen_urls = set()
    for j in initial_jobs or []:
        key = j.get("url", "") or f"{j.get('title', '')}|{j.get('company', '')}"
        if key not in seen_urls:
            seen_urls.add(key)
            all_jobs.append(j)
    if all_jobs:
        _score_jobs(all_jobs, keywords)
        _set_raw(sid, all_jobs)
        log(f"[SCRAPE] {len(all_jobs)} jobs served from cache instantly", sid)

    if not combos:
        # Pure cache-hit session — nothing left to scrape.
        update_session(sid, scraped=len(all_jobs))
        _save_elapsed(sid)
        update_session(sid, status="done")
        log(f"[SCRAPE] Cache-only session complete — {len(all_jobs)} jobs", sid)
        if not all_jobs:
            _set_raw(sid, [])
        return

    all_jobs, seen_urls = _scrape_combos(
        sid, combos, keywords=keywords, internship_mode=internship_mode,
        hours_old=hours_old, scrape_limit=scrape_limit, initial_jobs=all_jobs, seen_urls=seen_urls,
    )

    log(f"[SCRAPE] Pipeline complete — {len(all_jobs)} total jobs", sid)
    _harvest_companies(all_jobs)
    update_session(sid, scraped=len(all_jobs))
    _save_elapsed(sid)
    update_session(sid, status="done")

    if not all_jobs:
        _set_raw(sid, [])
        log(f"[SCRAPE] No jobs found", sid)


def _run_scrape_guarded(sid: str, *args, **kwargs):
    """Run run_scrape so the session always ends in a terminal status."""
    try:
        run_scrape(sid, *args, **kwargs)
    except Exception as e:
        log(f"[SCRAPE] Pipeline error: {e}", sid)
    finally:
        try:
            _save_elapsed(sid)
            update_session(sid, status="done")
        except Exception:
            pass


_CONFIG_COMBO_KEYS = None


def _is_config_combo(role, site, city, state, country, internship_mode, hours_old):
    """Check whether a combo is already covered by the config grid.
    Lazily builds the set on first call (O(1) lookups thereafter)."""
    global _CONFIG_COMBO_KEYS
    if _CONFIG_COMBO_KEYS is None:
        from scheduler import _grid_combos
        from db import _cache_key
        from config import CACHE_HOURS_OLD
        combos = _grid_combos()
        _CONFIG_COMBO_KEYS = set()
        for c in combos:
            key = _cache_key(c["role"], c["site"], c.get("city", "") or "",
                             c.get("state", "") or "", c.get("country", "") or "",
                             c.get("internship_mode", False), c.get("hours_old", CACHE_HOURS_OLD))
            _CONFIG_COMBO_KEYS.add(key)
    from db import _cache_key
    key = _cache_key(role, site, city or "", state or "", country or "",
                     1 if internship_mode else 0, hours_old)
    return key in _CONFIG_COMBO_KEYS


def _cache_lookup(req):
    """Split the requested grid into cache-served jobs + combos left to scrape.

    Returns (combos_to_scrape, initial_jobs, served_cache)."""
    from config import CACHE_ENABLED, CACHE_TTL_HOURS, CACHE_MIN_VOLUME
    from db import get_cache_entry, upsert_prewarm_combo, upsert_custom_prewarm, increment_combo_usage

    combos_to_scrape = []
    initial_jobs = []
    served_cache = 0

    for site in req.sites:
        for role in req.roles:
            combo = {
                "role": role, "site": site, "location": req.location or "",
                "indeed_country": req.indeed_country,
                "city": req.city or "", "state": req.state or "", "country": req.country or "",
            }
            if site not in SITE_MAP:
                combos_to_scrape.append(combo)
                continue
            if not CACHE_ENABLED or not (req.country or req.state or req.city):
                combos_to_scrape.append(combo)
                continue

            status, entry = get_cache_entry(
                role, site, req.city or "", req.state or "", req.country or "",
                req.internship_mode, req.hours_old,
                ttl_hours=CACHE_TTL_HOURS, min_volume=CACHE_MIN_VOLUME,
            )
            # Track usage for all combos (config grid + user-discovered)
            increment_combo_usage(
                role, site, req.city or "", req.state or "", req.country or "",
                req.internship_mode, req.hours_old,
            )
            if status in ("fresh", "stale"):
                for j in (entry.get("jobs") or []):
                    initial_jobs.append(j)
                served_cache += 1
                if status == "stale":
                    combos_to_scrape.append(dict(combo))  # serve + top-up
                continue

            combos_to_scrape.append(dict(combo))

            # Schedule it for prewarming
            upsert_prewarm_combo(
                role, site, req.city or "", req.state or "", req.country or "",
                req.internship_mode, req.hours_old,
            )
            # Persist user-searched combo if not already in config grid
            if not _is_config_combo(role, site, req.city or "", req.state or "",
                                    req.country or "", req.internship_mode, req.hours_old):
                upsert_custom_prewarm(
                    role, site, req.city or "", req.state or "", req.country or "",
                    req.internship_mode, req.hours_old,
                )

    return combos_to_scrape, initial_jobs, served_cache


_STATE_INDEX = None


def _state_cities(state: str, country: str = "") -> list:
    """Major cities for a state, used to city-scope Naukri searches.

    Naukri matches location tokens by city rather than state name, so each
    state-level Naukri combo loops the state's curated cities and merges the
    results under the state cache key. Returns [] (no loop, status quo) when
    the state has no curated list."""
    if not state:
        return []
    try:
        import config
        return list(config.CACHE_STATE_CITIES.get(state) or [])
    except Exception:
        return []


def _resolve_request_location(req):
    """Ensure req.state/country are set so the cache key aligns with the
    prewarm grid. Falls back to resolving free-text req.location against the
    same states/countries source the frontend dropdown uses."""
    global _STATE_INDEX
    if not (req.state or req.country) and not (req.location or "").strip():
        return req

    if _STATE_INDEX is None:
        _STATE_INDEX = {}
        try:
            from countrystatecity_countries import get_countries, get_states_of_country
            from api.routes.states import COMMON_COUNTRIES
            country_by_code = {c.iso2.lower(): c.name for c in get_countries()}
            for cc in COMMON_COUNTRIES:
                for s in get_states_of_country(cc):
                    _STATE_INDEX[s.name.strip().lower()] = {
                        "state": s.name,
                        "country": country_by_code.get(cc, cc.upper()),
                        "country_code": cc,
                    }
        except Exception:
            pass

    # State present but country missing -> fill from the index
    if req.state and not req.country:
        info = _STATE_INDEX.get(req.state.strip().lower())
        if info:
            req.state = info["state"]
            req.country = info["country_code"]

    # Neither present but location text given -> resolve it
    if not req.state and not req.country:
        text = (req.location or "").strip().lower()
        if text:
            import re as _re
            hit = None
            # 1) whole text is a state name
            if text in _STATE_INDEX:
                hit = _STATE_INDEX[text]
            # 2) a full state name appears as a standalone phrase in the text
            if hit is None:
                candidates = []
                for name, cand in _STATE_INDEX.items():
                    if _re.search(rf"(?<![a-z]){_re.escape(name)}(?![a-z])", text):
                        candidates.append((len(name), cand))
                if candidates:
                    candidates.sort(key=lambda x: x[0])
                    hit = candidates[0][1]
            # 3) whole text is a country name/code
            if hit is None:
                try:
                    from countrystatecity_countries import get_countries
                    for c in get_countries():
                        if c.name.lower() == text or c.iso2.lower() == text:
                            hit = {"state": "", "country": c.name, "country_code": c.iso2.lower()}
                            break
                except Exception:
                    pass
            # 4) text is a prefix of a state name (e.g. "Andaman")
            if hit is None:
                prefixes = [cand for name, cand in _STATE_INDEX.items()
                            if len(text) >= 3 and name.startswith(text)]
                if prefixes:
                    prefixes.sort(key=lambda c: len(c["state"]))
                    hit = prefixes[0]
            if hit:
                req.state = hit["state"] or ""
                req.country = hit["country_code"]
                if hit["state"]:
                    req.location = f"{hit['state']}, {hit['country']}"
    return req


@router.post("")
async def trigger_scrape(req: ScrapeRequest):
    if not req.search_id:
        return {"message": "Missing search_id", "status": "error"}
    sid = req.search_id
    _resolve_request_location(req)
    log(f"[SCRAPE] Search triggered — sites={req.sites}, "
          f"mode={'internship' if req.internship_mode else 'normal'}", sid)

    combos_to_scrape, initial_jobs, served_cache = _cache_lookup(req)
    if served_cache:
        log(f"[SCRAPE] {served_cache} combo(s) served from cache, {len(combos_to_scrape)} to scrape live", sid)

    if not combos_to_scrape:
        # 100% cache hit — complete synchronously so the first poll is instant.
        run_scrape(
            sid, req.sites, req.roles, req.location, req.indeed_country,
            keywords=req.keywords, internship_mode=req.internship_mode,
            user_email=req.user_email, resume_filename=req.resume_filename,
            resume_text=req.resume_text, scrape_limit=req.scrape_limit,
            hours_old=req.hours_old, city=req.city, state=req.state, country=req.country,
            combos=[], initial_jobs=initial_jobs,
        )
        return {"message": "Served from cache", "status": "done"}

    t = threading.Thread(target=_run_scrape_guarded, args=(
        sid, req.sites, req.roles, req.location, req.indeed_country,
    ), kwargs={
        "keywords": req.keywords,
        "internship_mode": req.internship_mode,
        "user_email": req.user_email,
        "resume_filename": req.resume_filename,
        "resume_text": req.resume_text,
        "scrape_limit": req.scrape_limit,
        "hours_old": req.hours_old,
        "city": req.city, "state": req.state, "country": req.country,
        "combos": combos_to_scrape,
        "initial_jobs": initial_jobs,
    }, daemon=True)
    t.start()
    return {"message": "Scrape started", "status": "running"}


@router.post("/stop")
async def stop_scrape(search_id: str = Query("")):
    if not search_id:
        return {"message": "Missing search_id", "status": "error"}
    s = get_session(search_id)
    if not s:
        return {"message": "Session not found", "status": "idle"}
    if s.get("status") != "running":
        return {"message": "Session already finished", "status": s.get("status", "idle")}
    log(f"[STOP] Stop requested for session {search_id}", search_id)
    update_session(search_id, cancel=True, status="done")
    return {"message": "Scrape cancelled", "status": "done"}


@router.get("/status")
async def scrape_status(search_id: str = Query("")):
    if not search_id:
        return {"status": "idle", "last_scrape_raw": 0, "queue_position": 0}
    s = get_session(search_id)
    if s is None:
        return {"status": "idle", "last_scrape_raw": 0, "queue_position": 0}
    from db import count_raw_jobs as _count_raw
    raw_count = _count_raw(search_id)
    return {
        "status": s.get("status", "idle"),
        "last_scrape_raw": s.get("scraped") or 0,
        "last_scrape_relevant": raw_count,
        "queue_position": s.get("queue_position", 0),
        "elapsed": s.get("elapsed_seconds", 0),
        "logs": get_events(search_id, limit=50),
    }

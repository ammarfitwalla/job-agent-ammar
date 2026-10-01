import os
import threading
import types
from typing import Optional
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Query, Request
from api.schemas import ScrapeRequest
from utils.logger import log
from utils.client_ip import get_client_ip
from utils.rate_limiter import check_rate_limit
from db import create_session, update_session, get_session, set_raw_jobs, get_events, _get_conn

router = APIRouter(prefix="/scrape", tags=["scrape"])

_STALE_TIMEOUT_MINUTES = 15

# Each triggered scrape spawns a thread that hits job sites and LLM-scoring;
# cap starts per IP to protect quota and fork-bombs.
_SCRAPE_RATE = 6
_SCRAPE_WINDOW = 60

# Per-combo scrape controls (overridable via config module).
SCRAPE_COMBO_STALL_SECONDS = 60   # cancel a combo if job count hasn't grown for this long
SCRAPE_GOOD_TARGET_PER_COMBO = 50  # stop a combo once it has collected this many new jobs


def _combo_knob(name: str, default):
    """Read a scrape-control knob from config if defined (avoids touching config.py)."""
    try:
        import config
        return getattr(config, name, default)
    except Exception:
        return default


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
                _complete_session(sid)
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


def _complete_session(sid, cancel=None):
    """Mark a session done and record elapsed. Session rows are kept indefinitely."""
    _save_elapsed(sid)
    kwargs = {"status": "done"}
    if cancel is not None:
        kwargs["cancel"] = cancel
    update_session(sid, **kwargs)


def _save_session_geo(sid, ip):
    """Resolve IP geolocation in the background and attach it to the session."""
    try:
        from db import _resolve_ip_sync, update_session as _db_update
        loc = _resolve_ip_sync(ip)
        if not (loc or {}).get("country"):
            return
        _db_update(sid, user_country=loc.get("country", ""),
                   user_city=loc.get("city", ""), user_region=loc.get("region", ""))
    except Exception:
        pass


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
    import time
    from match_engine.relevance_engine import role_match_count as _role_match
    from utils.delay import delay as _delay
    from utils.experience_level import detect_experience_level, level_from_job_level, yoe_bucket_from_job

    stall_seconds = _combo_knob("SCRAPE_COMBO_STALL_SECONDS", SCRAPE_COMBO_STALL_SECONDS)
    target = _combo_knob("SCRAPE_GOOD_TARGET_PER_COMBO", SCRAPE_GOOD_TARGET_PER_COMBO)

    all_jobs = list(initial_jobs or [])
    seen = set(seen_urls or [])
    combo_index = 0
    total_combos = len(combos)

    for combo in combos:
        combo_index += 1
        role = combo["role"]
        site_key = combo["site"]
        combo_new = 0
        enough = False
        stalled = False
        last_progress_ts = time.time()
        if sid and _is_cancelled(sid):
            log(f"[SCRAPE] Cancelled by user", sid)
            set_raw_jobs(sid, all_jobs)
            _complete_session(sid)
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
        runs = [{"location": _board_location(site_key, combo),
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
            if stall_seconds > 0 and time.time() - last_progress_ts > stall_seconds:
                log(f"[SCRAPE] Stalled — {role} @ {site_key}: no new jobs for {stall_seconds}s, skipping combo", sid)
                stalled = True
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
                    # Only empty feedback is a possible stall; never discard a
                    # batch that actually arrived with jobs (sync scrapers can
                    # block > the window before returning a full list).
                    if stall_seconds > 0 and time.time() - last_progress_ts > stall_seconds:
                        log(f"[SCRAPE] Stalled — {role} @ {site_key}: no new jobs for {stall_seconds}s, skipping combo", sid)
                        stalled = True
                        break
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
                    j["yoe_bucket"] = yoe_bucket_from_job(
                        j.get("title", ""), j.get("description", ""), j.get("job_level", ""))

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

                combo_new += new_count
                last_progress_ts = time.time()
                if target and combo_new >= target:
                    log(f"[SCRAPE] Enough relevant ({combo_new}) for {role} @ {site_key}, stopping combo", sid)
                    enough = True
                    break

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

            if stalled or enough:
                reason = "stalled — no new jobs" if stalled else f"target reached ({combo_new} jobs)"
                log(f"[SCRAPE] {role} @ {site_key}: combo ended ({reason})", sid)
                break

            # Pause between city runs to avoid Naukri rate-limiting
            if site_key == "naukri" and run_i < len(runs):
                log(f"[SCRAPE] {role} @ {site_key} — pausing before next city...", sid)
                _delay(6, 10)

        # Persist this combo's snapshot to the job cache, keyed by each job's
        # OWN location (as reported by the board) for all sites. A broad search
        # stores its jobs at city level when that is where they actually are;
        # nothing rolls up to a broader key. Remote / blank / unmatched jobs
        # fall back to the country-level row (never dropped).
        if combo_jobs:
            from config import CACHE_MAX_JOBS_PER_ENTRY
            from db import save_cache_entry, touch_prewarm_combo

            country_code = combo.get("country", "") or ""
            _ensure_states()
            global_city_map = _build_city_state_map(country_code)
            dbg = _debug_on("CACHE_DEBUG_FANOUT", "CACHE_DEBUG")
            if dbg:
                _debug(True, f"filing {len(combo_jobs)} jobs from combo "
                             f"role={role} site={site_key} country={country_code!r} "
                             f"searched_state={combo.get('state') or '-'!r} "
                             f"searched_city={combo.get('city') or '-'!r} "
                             f"| city_map[{country_code or '-'}]={len(global_city_map)} entries",
                      sid)
            location_groups: dict[tuple, list] = {}
            unresolved = []
            for j in combo_jobs:
                ck, sk, ir = _tag_job_location(j, country_code, global_city_map)
                j["_is_remote"] = ir
                location_groups.setdefault((ck, sk, ir), []).append(j)
                if not sk and not ir:
                    unresolved.append(j.get("location", ""))
            if dbg and unresolved:
                top = {}
                for loc in unresolved:
                    top[loc] = top.get(loc, 0) + 1
                shown = sorted(top.items(), key=lambda kv: -kv[1])[:12]
                _debug(True, f"  {len(unresolved)} job(s) had NO state in their "
                             f"location text -> filed under the country row "
                             f"(not under any state): {shown}",
                      sid)

            log(f"[SCRAPE] {role} @ {site_key}: distributing {len(combo_jobs)} jobs "
                f"across {len(location_groups)} location groups", sid)

            for (city_tag, state_tag, is_remote_tag), jobs in location_groups.items():
                if not jobs:
                    continue
                if dbg:
                    flag = " [REMOTE]" if is_remote_tag else ""
                    ex = jobs[0].get("location", "")
                    if state_tag:
                        _debug(True, f"  -> city={city_tag or '-'!r} state={state_tag!r}"
                                     f"{flag}: {len(jobs)} job(s) (e.g. {ex!r})", sid)
                    else:
                        _debug(True, f"  -> CITY ROW (state unknown) for country "
                                     f"{country_code!r}: {len(jobs)} job(s) "
                                     f"(e.g. {ex!r})", sid)
                try:
                    save_cache_entry(
                        role, site_key,
                        city_tag, state_tag, country_code,
                        internship_mode, hours_old, jobs,
                        max_jobs=CACHE_MAX_JOBS_PER_ENTRY, keep_larger=True,
                        is_remote=is_remote_tag,
                    )
                    touch_prewarm_combo(
                        role, site_key,
                        city_tag, state_tag, country_code,
                        internship_mode, hours_old,
                    )
                    remote_label = " [REMOTE]" if is_remote_tag else ""
                    log(f"[CACHE-INSERT] {role}@{site_key} city={city_tag} "
                        f"state={state_tag}{remote_label}: inserted {len(jobs)} jobs "
                        f"(urls={[j.get('url','')[:60] for j in jobs[:3]]}...)", sid)
                except Exception as e:
                    log(f"[CACHE-INSERT] {role}@{site_key} city={city_tag} "
                        f"state={state_tag}: FAILED to insert: {e}", sid)
            saved_cities = [(c, s) for (c, s, ir) in location_groups if c]
            saved_remote = sum(1 for (c, s, ir) in location_groups if ir)
            saved_country = sum(1 for (c, s, ir) in location_groups if not c and not ir)
            log(f"[SCRAPE] {role} @ {site_key}: saved {len(location_groups)} cache entries "
                f"(cities={saved_cities}, remote={saved_remote}, country={saved_country})", sid)
            # A dominant country row means most postings named only a city, so
            # state cells stay empty and those states keep re-scraping.
            if dbg and combo_jobs and saved_country:
                country_row_jobs = sum(
                    len(g) for (c, s, ir), g in location_groups.items() if not c and not ir)
                pct = int(100 * country_row_jobs / len(combo_jobs))
                if pct >= 20:
                    _debug(True, f"  NOTE {pct}% of jobs ({country_row_jobs}/"
                                 f"{len(combo_jobs)}) landed on the country row for "
                                 f"{country_code!r} -> its state cells may stay empty "
                                 f"and re-scrape. Add curated city lists for this "
                                 f"country to resolve them.", sid)

        # Staggered delay before next site/role combo
        _delay(*stagger)

    return all_jobs, seen


def run_scrape(sid, sites, roles, location, indeed_country,
               keywords=None, internship_mode=False, user_email="", resume_filename="", resume_text="",
               scrape_limit=200, hours_old=168, city="", state="", country="",
               combos=None, initial_jobs=None, client_ip=""):
    from db import set_raw_jobs as _set_raw

    create_session(sid, sites=sites, keywords=keywords or [], roles=roles or [],
                   keywords_count=len(keywords or []), roles_count=len(roles or []),
                   user_email=user_email,
                   location=location or "", internship_mode=internship_mode,
                   ip_address=client_ip or "")
    from db import get_user as _get_user
    session_resume = resume_filename or ""
    if not session_resume and user_email:
        u = _get_user(user_email)
        session_resume = (u or {}).get("resume_filename") or ""
    update_session(sid, status="running", cancel=False, resume_filename=session_resume)
    _save_resume_text(sid, resume_text)
    if client_ip:
        threading.Thread(target=_save_session_geo, args=(sid, client_ip), daemon=True).start()

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
        _complete_session(sid)
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
    _complete_session(sid)

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
            _complete_session(sid)
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


def _debug(on: bool, message: str, sid: str = None) -> None:
    """Verbose tracing for the country fan-out.

    Off unless CACHE_DEBUG_FANOUT is on in config (or CACHE_DEBUG is on, which
    turns on every cache debug flag). Goes to the same stdout + session timeline
    as log(), so it is visible while testing and switchable off in production.
    """
    if not on:
        return
    log(f"[CACHE-DEBUG] {message}", sid)


def _debug_on(*names: str) -> bool:
    """True when any of the given config debug flags is enabled."""
    try:
        import config
        return any(bool(getattr(config, n, False)) for n in names)
    except Exception:
        return False


def _top_states_for(country: str) -> list:
    """Curated highest-volume states for a country (config.CACHE_TOP_STATES).

    Only used for country-only searches. Returns [] for unknown countries, which
    makes the caller fall back to plain country-scope behaviour."""
    cc = (country or "").lower()
    if not cc:
        return []
    try:
        import config
        return [s.strip() for s in (getattr(config, "CACHE_TOP_STATES", {}) or {}).get(cc, []) if s.strip()]
    except Exception:
        return []


def _scope_fresh(status: str, entry: dict, min_volume: int) -> bool:
    """Whether a per-state scope is genuinely covered.

    `get_cached_jobs_aggregate` reports 'fresh' when ANY child row is fresh, and
    merges each row's job_count. A state whose union clears min_volume purely by
    adding several sub-threshold rows is not really covered, so require the
    merged count to clear the bar as well."""
    if status != "fresh":
        return False
    try:
        return int((entry or {}).get("job_count") or 0) >= int(min_volume)
    except Exception:
        return True


def _cache_lookup(req):
    """Split the requested grid into cache-served jobs + combos left to scrape.

    For Naukri state-level searches, decomposes into per-city lookups so that
    fresh city entries are served immediately and only stale/missing cities
    trigger live scraping.

    For country-only searches (no state, no city) with a CACHE_TOP_STATES entry,
    fans out across the country's five top states: each state's cache cell is
    evaluated independently, so a country row that is 'fresh' only because of one
    child still refreshes the states that were never populated. Coverage counts
    are returned in the 4th element.

    Returns (combos_to_scrape, initial_jobs, served_cache, coverage)."""
    from config import CACHE_ENABLED, CACHE_TTL_HOURS, CACHE_MIN_VOLUME
    from db import get_cache_entry, get_cached_jobs_aggregate, upsert_prewarm_combo, upsert_custom_prewarm, increment_combo_usage, increment_custom_prewarm_usage

    combos_to_scrape = []
    initial_jobs = []
    served_cache = 0
    # Aggregate per-site/role fan-out coverage so a search with several roles or
    # boards reports the weakest scope rather than summing them.
    state_totals = set()
    states_fresh = set()
    states_stale = set()
    states_missing = set()

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

            # --- Country-only fan-out across curated top states ---
            top_states = [] if (req.state or req.city) else _top_states_for(req.country)
            dbg = _debug_on("CACHE_DEBUG_FANOUT", "CACHE_DEBUG")
            if dbg:
                _debug(True, f"request={req.sites} roles={req.roles} "
                             f"location={req.location!r} city={req.city!r} "
                             f"state={req.state!r} country={req.country!r} "
                             f"-> top_states={top_states}",
                      getattr(req, "_search_id", None))
            if top_states:
                # The country-exact scope is evaluated FIRST, before any
                # increment_combo_usage call. Those calls upsert a placeholder
                # job_cache row (job_count=0), which would make this scope look
                # 'stale' and mask its genuinely missing state.
                status, entry = get_cached_jobs_aggregate(
                    role, site, "", "", req.country,
                    req.internship_mode, req.hours_old,
                    ttl_hours=CACHE_TTL_HOURS, min_volume=CACHE_MIN_VOLUME,
                )
                _debug(dbg, f"{role}@{site} COUNTRY-EXACT status={status} "
                            f"jobs={len((entry or {}).get('jobs') or [])}",
                      getattr(req, "_search_id", None))
                increment_combo_usage(
                    role, site, "", "", req.country,
                    req.internship_mode, req.hours_old,
                )
                if not _is_config_combo(role, site, "", "", req.country,
                                        req.internship_mode, req.hours_old):
                    increment_custom_prewarm_usage(
                        role, site, "", "", req.country,
                        req.internship_mode, req.hours_old,
                    )
                # Serves jobs no state search attributes to a state, e.g. bare
                # "Saudi Arabia" or "Riyadh Region".
                if status in ("fresh", "stale"):
                    for j in (entry.get("jobs") or []):
                        initial_jobs.append(j)
                    served_cache += 1
                    if status == "stale":
                        combos_to_scrape.append(dict(combo))
                else:
                    combos_to_scrape.append(dict(combo))
                    upsert_prewarm_combo(
                        role, site, "", "", req.country,
                        req.internship_mode, req.hours_old,
                    )
                    if not _is_config_combo(role, site, "", "", req.country,
                                            req.internship_mode, req.hours_old):
                        upsert_custom_prewarm(
                            role, site, "", "", req.country,
                            req.internship_mode, req.hours_old,
                        )

                for state_name in top_states:
                    state_combo = dict(combo)
                    state_combo["state"] = state_name
                    state_combo["location"] = state_name
                    status, entry = get_cached_jobs_aggregate(
                        role, site, "", state_name, req.country,
                        req.internship_mode, req.hours_old,
                        ttl_hours=CACHE_TTL_HOURS, min_volume=CACHE_MIN_VOLUME,
                    )
                    increment_combo_usage(
                        role, site, "", state_name, req.country,
                        req.internship_mode, req.hours_old,
                    )
                    if not _is_config_combo(role, site, "", state_name, req.country,
                                            req.internship_mode, req.hours_old):
                        increment_custom_prewarm_usage(
                            role, site, "", state_name, req.country,
                            req.internship_mode, req.hours_old,
                        )
                    if status in ("fresh", "stale"):
                        for j in (entry.get("jobs") or []):
                            initial_jobs.append(j)
                        served_cache += 1
                    scope_fresh = _scope_fresh(status, entry, CACHE_MIN_VOLUME)
                    _debug(dbg, f"{role}@{site} state={state_name!r} "
                                f"cache={status} jobs={len((entry or {}).get('jobs') or [])} "
                                f"min_volume={CACHE_MIN_VOLUME} "
                                f"-> {'FRESH (served, no scrape)' if scope_fresh else (status.upper() + ' (served + top-up)' if status == 'stale' else 'MISSING (will scrape)')}",
                          getattr(req, "_search_id", None))
                    if scope_fresh:
                        states_fresh.add(state_name)
                        continue
                    # stale serves now and tops up; missing is scraped anyway
                    if status == "stale":
                        states_stale.add(state_name)
                    else:
                        states_missing.add(state_name)
                    combos_to_scrape.append(dict(state_combo))
                    upsert_prewarm_combo(
                        role, site, "", state_name, req.country,
                        req.internship_mode, req.hours_old,
                    )
                    if not _is_config_combo(role, site, "", state_name, req.country,
                                            req.internship_mode, req.hours_old):
                        upsert_custom_prewarm(
                            role, site, "", state_name, req.country,
                            req.internship_mode, req.hours_old,
                        )
                state_totals.update(top_states)

                log(f"[CACHE] fan-out {role}@{site}/{req.country}: "
                    f"fresh={sorted(states_fresh & set(top_states))}, "
                    f"stale={sorted(states_stale & set(top_states))}, "
                    f"missing={sorted(states_missing & set(top_states))}",
                    req._search_id if hasattr(req, '_search_id') else None)
                _debug(dbg, f"{role}@{site}/{req.country} SUMMARY "
                            f"fresh={sorted(states_fresh & set(top_states))} "
                            f"stale={sorted(states_stale & set(top_states))} "
                            f"missing={sorted(states_missing & set(top_states))} "
                            f"| combos_to_scrape={len(combos_to_scrape)} "
                            f"cached_jobs_so_far={len(initial_jobs)} "
                            f"unique_urls={len({j.get('url') for j in initial_jobs})}",
                      getattr(req, "_search_id", None))
                continue

            # --- Naukri state-level: decompose into per-city lookups ---
            if site == "naukri" and not req.city and req.state:
                cities = _state_cities(req.state, req.country)
                if cities:
                    fresh_cities = []
                    stale_cities = []
                    missing_cities = []

                    for city_name in cities:
                        increment_combo_usage(
                            role, site, city_name, req.state, req.country,
                            req.internship_mode, req.hours_old,
                        )
                        status, entry = get_cache_entry(
                            role, site, city_name, req.state, req.country,
                            req.internship_mode, req.hours_old,
                            ttl_hours=CACHE_TTL_HOURS, min_volume=CACHE_MIN_VOLUME,
                        )
                        if status in ("fresh", "stale"):
                            for j in (entry.get("jobs") or []):
                                initial_jobs.append(j)
                            served_cache += 1
                        if status == "fresh":
                            fresh_cities.append(city_name)
                        elif status == "stale":
                            stale_cities.append(city_name)
                            combos_to_scrape.append({
                                "role": role, "site": site,
                                "location": city_name,
                                "indeed_country": req.indeed_country,
                                "city": city_name, "state": req.state, "country": req.country,
                            })
                        else:
                            missing_cities.append(city_name)
                            combos_to_scrape.append({
                                "role": role, "site": site,
                                "location": city_name,
                                "indeed_country": req.indeed_country,
                                "city": city_name, "state": req.state, "country": req.country,
                            })

                    log(f"[CACHE] Naukri {role}@{req.state}: fresh={fresh_cities}, "
                        f"stale={stale_cities}, missing={missing_cities}", req._search_id if hasattr(req, '_search_id') else None)
                    if fresh_cities or stale_cities:
                        # Already served, only scrape the rest
                        continue
                    # All missing — fall through to scrape with the original state combo
                    # (generates city loops in _scrape_combos)
                    combos_to_scrape.append(dict(combo))
                    continue

                # No curated cities — fall back to state-level combo
                status, entry = get_cached_jobs_aggregate(
                    role, site, "", req.state, req.country,
                    req.internship_mode, req.hours_old,
                    ttl_hours=CACHE_TTL_HOURS, min_volume=CACHE_MIN_VOLUME,
                )
                increment_combo_usage(
                    role, site, "", req.state, req.country,
                    req.internship_mode, req.hours_old,
                )
                if not _is_config_combo(role, site, "", req.state, req.country,
                                        req.internship_mode, req.hours_old):
                    increment_custom_prewarm_usage(
                        role, site, "", req.state, req.country,
                        req.internship_mode, req.hours_old,
                    )
                if status in ("fresh", "stale"):
                    for j in (entry.get("jobs") or []):
                        initial_jobs.append(j)
                    served_cache += 1
                    if status == "stale":
                        combos_to_scrape.append(dict(combo))
                    continue

                combos_to_scrape.append(dict(combo))
                upsert_prewarm_combo(
                    role, site, "", req.state, req.country,
                    req.internship_mode, req.hours_old,
                )
                if not _is_config_combo(role, site, "", req.state, req.country,
                                        req.internship_mode, req.hours_old):
                    upsert_custom_prewarm(
                        role, site, "", req.state, req.country,
                        req.internship_mode, req.hours_old,
                    )
                continue

            # --- All other sites / city-level Naukri: exact + finer-grained aggregation ---
            status, entry = get_cached_jobs_aggregate(
                role, site, req.city or "", req.state or "", req.country or "",
                req.internship_mode, req.hours_old,
                ttl_hours=CACHE_TTL_HOURS, min_volume=CACHE_MIN_VOLUME,
            )
            # Track usage for all combos (config grid + user-discovered)
            increment_combo_usage(
                role, site, req.city or "", req.state or "", req.country or "",
                req.internship_mode, req.hours_old,
            )
            if not _is_config_combo(role, site, req.city or "", req.state or "",
                                    req.country or "", req.internship_mode, req.hours_old):
                increment_custom_prewarm_usage(
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

    coverage = {
        "states_total": len(state_totals),
        "states_fresh": len(state_totals & states_fresh),
        "states_stale": len(state_totals & states_stale),
        "states_missing": len(state_totals & states_missing),
        "complete": bool(state_totals) and not (state_totals - states_fresh),
    }
    _debug(_debug_on("CACHE_DEBUG_FANOUT", "CACHE_DEBUG"),
           f"TOTAL combos_to_scrape={len(combos_to_scrape)} "
           f"cached_jobs={len(initial_jobs)} "
           f"unique_urls={len({j.get('url') for j in initial_jobs})} "
           f"served={served_cache} coverage={coverage}")
    return combos_to_scrape, initial_jobs, served_cache, coverage


_STATE_INDEX = None
_STATE_CODE_INDEX = {}
_CITY_INDEX = None
_CITY_READY = False
_CITY_LOCK = threading.Lock()
_COUNTRY_CODE_TO_NAME = {}
_city_state_map_cache = {}


def _ensure_states():
    """Build (once) the country-name map and state index synchronously (fast).
    Calls from the request path must not block on the full city index."""
    global _STATE_INDEX, _STATE_CODE_INDEX, _COUNTRY_CODE_TO_NAME
    if _STATE_INDEX is not None:
        return _STATE_INDEX
    _STATE_INDEX = {}
    _STATE_CODE_INDEX = {}
    _COUNTRY_CODE_TO_NAME = {}
    try:
        from countrystatecity_countries import get_countries, get_states_of_country
        from api.routes.states import COMMON_COUNTRIES
        for c in get_countries():
            _COUNTRY_CODE_TO_NAME[c.iso2.lower()] = c.name
        for cc in COMMON_COUNTRIES:
            country_name = _COUNTRY_CODE_TO_NAME.get(cc, cc.upper())
            try:
                for s in get_states_of_country(cc):
                    info = {
                        "state": s.name,
                        "country": country_name,
                        "country_code": cc,
                    }
                    _STATE_INDEX[s.name.strip().lower()] = info
                    code = (getattr(s, "state_code", "") or "").strip().lower()
                    if not code:
                        iso = getattr(s, "iso3166_2", "") or ""
                        code = (iso.split("-")[-1] if "-" in iso else "").lower()
                    if code and len(code) >= 2:
                        _STATE_CODE_INDEX.setdefault(code, info)
            except Exception:
                pass
    except Exception:
        pass
    return _STATE_INDEX


def _build_city_index():
    """Build the {lowercase_city: [candidates]} index over COMMON_COUNTRIES.
    Slow (~7s), so run it in a background thread. A city name maps to every
    matching city across countries (US first) so structured resolutions can
    pick the right one via its state/country segments."""
    global _CITY_INDEX, _CITY_READY
    if _CITY_READY:
        return
    _CITY_INDEX = {}
    _ensure_states()
    try:
        from countrystatecity_countries import get_states_of_country, get_cities_of_country
        from api.routes.states import COMMON_COUNTRIES
        for cc in COMMON_COUNTRIES:
            try:
                state_name = {}
                state_code_name = {}
                for s in get_states_of_country(cc):
                    state_name[s.state_code.strip().lower()] = s.name
                for sc_code, s_name in state_name.items():
                    state_code_name[s_name.strip().lower()] = sc_code
                country_name = _COUNTRY_CODE_TO_NAME.get(cc, cc.upper())
                for c in get_cities_of_country(cc):
                    key = c.name.strip().lower()
                    sc = c.state_code.strip().lower()
                    st = state_name.get(sc, "")
                    _CITY_INDEX.setdefault(key, []).append({
                        "city": c.name,
                        "state": st,
                        "state_code": state_code_name.get(st.strip().lower(), sc.upper()),
                        "country": country_name,
                        "country_code": cc,
                    })
            except Exception:
                pass
    except Exception:
        pass
    finally:
        _CITY_READY = True


def _ensure_cities():
    """Kick the background city-index build if not running; callers tolerate a
    partial/empty index until it's ready."""
    if not _CITY_READY and _CITY_LOCK.acquire(blocking=False):
        try:
            _build_city_index()
        finally:
            _CITY_LOCK.release()
    return _CITY_INDEX or {}


# Warm the city index in the background as soon as the module loads, so the
# first scrape usually finds it ready.
if _CITY_INDEX is None:
    threading.Thread(target=_ensure_cities, daemon=True, name="city-index").start()


def _st_matches(cand, hint):
    return bool(hint) and (
        cand["state"].lower() == hint
        or (cand.get("state_code") or "").lower() == hint
        or cand["state"].lower().startswith(hint)
        or hint.startswith(cand["state"].lower())
    )


def _co_matches(cand, hint):
    return bool(hint) and (cand["country_code"] == hint or cand["country"].lower() == hint)


def _pick_city(cands, rest=()):
    """Pick the right city from colliding city names using the remaining
    'State, Country' segments of the typed text."""
    rest = [x.strip().lower() for x in rest if x.strip()]
    state_hint = rest[0] if len(rest) >= 1 else ""
    country_hint = rest[1] if len(rest) >= 2 else ""
    for c in cands:
        if state_hint and country_hint and _st_matches(c, state_hint) and _co_matches(c, country_hint):
            return c
    for c in cands:
        if state_hint and _st_matches(c, state_hint):
            return c
    for c in cands:
        if country_hint and _co_matches(c, country_hint):
            return c
    return cands[0]


def _city_hit_for(text):
    """City-index entry for the given lowercase text, or None (prefix match on
    >=3 chars). Returns the US-first default when names collide."""
    index = _CITY_INDEX or {}
    if not text or len(text) < 2:
        return None
    if text in index:
        return index[text][0]
    if len(text) >= 3:
        best = None
        for name, cands in index.items():
            if name.startswith(text):
                if best is None or len(name) < len(best):
                    best = name
        if best:
            return index[best][0]
    return None


def _board_location(site_key, combo):
    """Location token each board actually searches with.

    Naukri matches bare city/state tokens; Indeed's 'l=' behaves best with the
    fullest 'City, State, Country'; LinkedIn prefers 'City, State'."""
    _ensure_states()
    city = (combo.get("city") or "").strip()
    state = (combo.get("state") or "").strip()
    country_code = (combo.get("country") or "").strip()
    country_name = _COUNTRY_CODE_TO_NAME.get(country_code.lower()) or country_code or ""
    parts = [p for p in (city, state) if p]
    if site_key == "naukri":
        return (parts[0] if parts else country_name) or "India"
    if site_key == "linkedin":
        return ", ".join(parts) or country_name or "United States"
    if site_key == "indeed":
        return ", ".join(p for p in (city, state, country_name) if p) or "United States"
    return ", ".join(p for p in (city, state, country_name) if p) or "United States"


def _build_city_state_map(country_code: str = "") -> dict:
    """Build a {lowercase_city: (canonical_city, state_name)} map from
    CACHE_STATE_CITIES, limited to the requested country. Cached per country code.

    Scoped deliberately: _tag_job_location matches this map by bare substring
    BEFORE the country-filtered _STATE_INDEX, so a merged map files foreign jobs
    under the wrong state (a US job in "Salem, Oregon" tagged Salem/Tamil Nadu,
    and saved against country_code="us" with state="Tamil Nadu"). The country
    itself never comes from the job text, so restricting the map by country is
    enough to keep the pairing honest.

    Falls back to the unfiltered map when the state index is unavailable, and
    skips states it cannot attribute to the requested country.
    """
    cc = (country_code or "").lower()
    if cc in _city_state_map_cache:
        return _city_state_map_cache[cc]
    try:
        import config
        _ensure_states()
        index = _STATE_INDEX or {}
        m = {}
        for state, cities in config.CACHE_STATE_CITIES.items():
            if cc and index:
                info = index.get((state or "").strip().lower())
                if not info or (info.get("country_code") or "").lower() != cc:
                    continue
            for city in cities:
                m[city.lower()] = (city, state)
        _city_state_map_cache[cc] = m
    except Exception:
        m = {}
    return m


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


_REMOTE_LOCATION_TOKENS = ("remote", "work from home", "work from anywhere")


def _tag_job_location(j, country_code, global_city_map=None):
    """Resolve the cache row location (city, state, is_remote) for a scraped
    job from its OWN location text, as returned by the board.

    Remote markers → city/state blank + is_remote=1. Otherwise the location is
    matched against the searched country's curated city tokens (exact token
    substring), then the full-name state index, then 2-letter state codes
    (e.g. 'MH' → Maharashtra) as whole tokens — all same-country only.
    Unmatched / blank locations fall back to the country-level row
    (city/state blank, non-remote) — a job is never dropped here.
    """
    jloc = (j.get("location") or "").strip().lower()
    if any(t in jloc for t in _REMOTE_LOCATION_TOKENS):
        return "", "", 1
    city = ""
    state = ""
    if jloc:
        for token, (canonical, st) in (global_city_map or {}).items():
            if token and token in jloc:
                city = canonical
                state = st
                break
        if not city and _STATE_INDEX:
            ccl = (country_code or "").lower()
            for name, info in _STATE_INDEX.items():
                if name in jloc and (not ccl or info.get("country_code", "").lower() == ccl):
                    state = info["state"]
                    break
        if not state and _STATE_CODE_INDEX:
            ccl = (country_code or "").lower()
            for tok in _tokenize_location(jloc):
                if len(tok) < 2:
                    continue
                info = _STATE_CODE_INDEX.get(tok)
                if info and (not ccl or info.get("country_code", "").lower() == ccl):
                    state = info["state"]
                    break
    return city, state, 0


def _tokenize_location(jloc):
    """Word tokens of a lowercase location string, split on non-alphanumerics.
    Used to match 2-letter state codes (e.g. 'mh') as whole tokens so short
    codes never substring-match inside longer words."""
    return "".join(ch if ch.isalnum() else " " for ch in jloc).split()


def _resolve_request_location(req):
    """Ensure req.state/country/city are set so the cache key aligns with the
    prewarm grid. Falls back to resolving free-text req.location against the
    same states/countries source the frontend dropdown uses; a typed city is
    resolved into req.city (with its state/country) so it keys its own cache cell."""
    if not (req.state or req.country or req.city) and not (req.location or "").strip():
        return req
    _ensure_states()
    city_index = _CITY_INDEX or {}

    # City given but state/country missing -> fill from the city index.
    if req.city and (not req.state or not req.country):
        cands = city_index.get(req.city.strip().lower())
        if cands:
            info = cands[0]
            req.city = info["city"] or req.city
            req.state = info["state"] or req.state
            req.country = info["country_code"] or req.country

    # State present but country missing -> fill from the states index.
    if req.state and not req.country:
        info = _STATE_INDEX.get(req.state.strip().lower())
        if info:
            req.state = info["state"]
            req.country = info["country_code"]

    if not req.state and not req.country:
        text = (req.location or "").strip().lower()
        if text:
            import re as _re
            hit = None
            # 0) whole text is a state name (exact state beats same-named city)
            if text in _STATE_INDEX:
                hit = _STATE_INDEX[text]
            # 1) whole text is a city name
            if hit is None and text in city_index:
                hit = city_index[text][0]
            # 2) first comma segment is a city name ("City, State, Country")
            if hit is None:
                segs = [x.strip() for x in text.split(",") if x.strip()]
                cands = city_index.get(segs[0]) if segs else None
                if cands:
                    hit = _pick_city(cands, segs[1:])
            # 3) a full state name appears as a standalone phrase in the text
            if hit is None:
                candidates = []
                for name, cand in _STATE_INDEX.items():
                    if _re.search(rf"(?<![a-z]){_re.escape(name)}(?![a-z])", text):
                        candidates.append((len(name), cand))
                if candidates:
                    candidates.sort(key=lambda x: x[0])
                    hit = candidates[0][1]
            # 4) whole text is a country name/code
            if hit is None:
                for code, name in _COUNTRY_CODE_TO_NAME.items():
                    if name.lower() == text or code.lower() == text:
                        hit = {"state": "", "country": name, "country_code": code}
                        break
            # 5) text is a prefix of a state name (e.g. "Andaman")
            if hit is None:
                prefixes = [cand for name, cand in _STATE_INDEX.items()
                            if len(text) >= 3 and name.startswith(text)]
                if prefixes:
                    prefixes.sort(key=lambda c: len(c["state"]))
                    hit = prefixes[0]
            # 6) text is a prefix of a city name
            if hit is None:
                hit = _city_hit_for(text)
            if hit:
                if hit.get("city"):
                    req.city = hit["city"] or ""
                    req.state = hit["state"] or ""
                    req.country = hit["country_code"]
                    req.location = ", ".join(
                        p for p in (hit["city"], hit["state"], hit["country"]) if p)
                else:
                    req.state = hit["state"] or ""
                    req.country = hit["country_code"]
                    if hit["state"]:
                        req.location = f"{hit['state']}, {hit['country']}"
    return req


@router.post("")
async def trigger_scrape(req: ScrapeRequest, request: Request = None):
    if not req.search_id:
        return {"message": "Missing search_id", "status": "error"}
    client_ip = get_client_ip(request)
    if client_ip and not check_rate_limit(f"scrape:{client_ip}", _SCRAPE_RATE, _SCRAPE_WINDOW):
        raise HTTPException(429, "Too many requests. Try again later.")
    sid = req.search_id
    _resolve_request_location(req)
    log(f"[SCRAPE] Search triggered — sites={req.sites}, "
          f"mode={'internship' if req.internship_mode else 'normal'}", sid)

    combos_to_scrape, initial_jobs, served_cache, coverage = _cache_lookup(req)
    if served_cache:
        log(f"[SCRAPE] {served_cache} combo(s) served from cache, {len(combos_to_scrape)} to scrape live", sid)
    if coverage.get("states_total"):
        log(f"[SCRAPE] top-state coverage {coverage}", sid)

    if not combos_to_scrape:
        # 100% cache hit — complete synchronously so the first poll is instant.
        run_scrape(
            sid, req.sites, req.roles, req.location, req.indeed_country,
            keywords=req.keywords, internship_mode=req.internship_mode,
            user_email=req.user_email, resume_filename=req.resume_filename,
            resume_text=req.resume_text, scrape_limit=req.scrape_limit,
            hours_old=req.hours_old, city=req.city, state=req.state, country=req.country,
            combos=[], initial_jobs=initial_jobs, client_ip=client_ip,
        )
        return {"message": "Served from cache", "status": "done",
                "top_states_coverage": coverage}

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
        "client_ip": client_ip,
    }, daemon=True)
    t.start()
    return {"message": "Scrape started", "status": "running",
            "top_states_coverage": coverage}


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
        "resume_filename": s.get("resume_filename", ""),
        "logs": get_events(search_id, limit=50),
    }

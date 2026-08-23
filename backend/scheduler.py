"""Feature B — self-healing prewarm scheduler.

Scrapes the prewarm_queue grid (30 roles x all states of in/us/ie/ae x boards
x both modes) in the background, capped per run by PREWARM_MAX_COMBOS_PER_RUN,
with per-board concurrency limits. Results land in the job_cache table so user
searches hit instantly.

A DB-backed leader lock keeps only one process prewarming when multiple
backend processes share the same database.
"""
import os
import socket
import threading
from datetime import datetime

from utils.logger import log

_INDEED_COUNTRY = {"in": "India", "us": "USA", "ie": "Ireland", "ae": "united arab emirates"}
_OWNER = f"{socket.gethostname()}:{os.getpid()}"
_scheduler = None


def _grid_combos():
    """Full prewarm grid from config: CACHE_ROLES x states x sites x both modes.
    Custom roles from the DB are merged in so they get prewarmed too.
    User-searched combos from custom_prewarm are appended (deduped)."""
    import config
    import db
    from countrystatecity_countries import get_states_of_country

    # Merge predefined + custom roles (deduped, case-insensitive)
    seen_roles = set()
    roles = []
    for r in config.CACHE_ROLES:
        key = r.lower()
        if key not in seen_roles:
            seen_roles.add(key)
            roles.append(r)
    for r in db.get_custom_roles():
        key = r.lower()
        if key not in seen_roles:
            seen_roles.add(key)
            roles.append(r)

    combos = []
    exclude = set(config.CACHE_STATES_EXCLUDE)
    for country in config.CACHE_COUNTRIES:
        country = (country or "").strip().lower()
        if not country:
            continue
        if config.CACHE_INCLUDE_ALL_STATES and not config.CACHE_STATES_OVERRIDE.get(country):
            states = [s.name for s in get_states_of_country(country.upper())]
        else:
            states = list(config.CACHE_STATES_OVERRIDE.get(country, []))
        states = [s for s in states if s not in exclude]
        if not states:
            continue
        sites = config.CACHE_SITES_INDIA if country == "in" else config.CACHE_SITES_DEFAULT
        for state in states:
            for role in roles:
                for site in sites:
                    # For Naukri, expand state combos into per-city combos
                    # so each city gets its own cache entry.
                    if site == "naukri":
                        cities = config.CACHE_STATE_CITIES.get(state) or []
                        if cities:
                            for city in cities:
                                for mode in (False, True):
                                    combos.append({
                                        "role": role, "site": site, "city": city,
                                        "state": state, "country": country,
                                        "internship_mode": mode,
                                        "hours_old": config.CACHE_HOURS_OLD,
                                        "source": "config",
                                        "location": city,
                                        "indeed_country": _INDEED_COUNTRY.get(country, "USA"),
                                    })
                            continue
                    for mode in (False, True):
                        combos.append({
                            "role": role, "site": site, "city": "",
                            "state": state, "country": country,
                            "internship_mode": mode,
                            "hours_old": config.CACHE_HOURS_OLD,
                            "source": "config",
                            "location": state,
                            "indeed_country": _INDEED_COUNTRY.get(country, "USA"),
                        })

    # Build dedup set from config combos
    config_keys = set()
    for c in combos:
        config_keys.add((c["role"], c["site"], c.get("city", "") or "",
                         c.get("state", "") or "", c.get("country", "") or "",
                         c.get("internship_mode", False), c.get("hours_old", 168)))

    # Append user-searched combos from custom_prewarm (skip any already in config grid)
    for row in db.get_custom_prewarm():
        ck = (row["role"], row["site"], row["city"] or "", row["state"] or "",
              row["country"] or "", row["internship_mode"], row["hours_old"])
        if ck in config_keys:
            continue
        country_code = (row["country"] or "").lower()
        combos.append({
            "role": row["role"], "site": row["site"],
            "city": row["city"] or "", "state": row["state"] or "",
            "country": country_code,
            "internship_mode": row["internship_mode"],
            "hours_old": row["hours_old"],
            "source": "custom",
            "location": row["city"] or row["state"] or row["country"],
            "indeed_country": _INDEED_COUNTRY.get(country_code, "USA"),
        })

    return combos


_STALE_LOCK_SECONDS = 180      # a dead owner is taken over after this long
_HEARTBEAT_INTERVAL = 45       # seconds between lock heartbeats
_own_lock = False


def _owner_alive(owner_id: str):
    """Check whether a same-host lock owner's PID is still alive.
    Returns True/False for same-host owners, None for foreign hosts."""
    try:
        host, pid_s = owner_id.rsplit(":", 1)
        if host != socket.gethostname():
            return None
        pid = int(pid_s)
        try:
            os.kill(pid, 0)
            return True
        except OSError as e:
            # errno 13 = process exists but we lack access to signal it
            return getattr(e, "errno", None) == 13
    except Exception:
        return None


def _heartbeat(stale_after_seconds: float = _STALE_LOCK_SECONDS) -> bool:
    """Renew/acquire the single-owner prewarm lock. Returns True if we own it."""
    from db import _get_conn

    now = datetime.utcnow().isoformat()
    with _get_conn() as (conn, cur):
        cur.execute("SELECT owner, last_heartbeat FROM scheduler_lock WHERE id = 1")
        row = cur.fetchone()
        if row is None:
            cur.execute(
                "INSERT INTO scheduler_lock (id, owner, started_at, last_heartbeat) VALUES (1, ?, ?, ?)",
                (_OWNER, now, now),
            )
            conn.commit()
            return True
        if row["owner"] == _OWNER:
            cur.execute("UPDATE scheduler_lock SET last_heartbeat = ? WHERE id = 1", (now,))
            conn.commit()
            return True
        try:
            age = (datetime.utcnow() - datetime.fromisoformat(row["last_heartbeat"])).total_seconds()
        except Exception:
            age = 1e18
        alive = _owner_alive(row["owner"])
        dead_same_host = alive is False
        # Take over if: owner PID is dead on this host (instant), or the owner is
        # unreachable/foreign and stale, or the owner is alive but ancient.
        if dead_same_host or age > stale_after_seconds or (alive is True and age > 6 * 3600):
            cur.execute(
                "UPDATE scheduler_lock SET owner = ?, started_at = ?, last_heartbeat = ? WHERE id = 1",
                (_OWNER, now, now),
            )
            conn.commit()
            return True
        return False


def _release_lock():
    """Clear the lock row only if we are the current owner."""
    from db import _get_conn

    with _get_conn() as (conn, cur):
        cur.execute("DELETE FROM scheduler_lock WHERE id = 1 AND owner = ?", (_OWNER,))
        conn.commit()


def _start_heartbeat_loop():
    """Keep refreshing our lock ownership so another process can take over
    quickly if this one dies or is reloaded."""

    def _loop():
        global _own_lock
        while True:
            if _own_lock:
                try:
                    _own_lock = _heartbeat()
                except Exception:
                    pass
            threading.Event().wait(_HEARTBEAT_INTERVAL)

    t = threading.Thread(target=_loop, daemon=True)
    t.start()


def _run_workers(combos, config):
    import queue as _queue
    from api.routes.scrape import _scrape_combos, SITE_MAP

    q = _queue.Queue()
    for c in combos:
        q.put(c)
    semaphores = {board: threading.BoundedSemaphore(config.MAX_CONCURRENT_PER_BOARD.get(board, 1))
                  for board in SITE_MAP}
    fallback_sema = threading.Lock()
    workers = max(1, int(config.PREWARM_WORKERS))

    def worker():
        from db import get_cache_entry

        while True:
            try:
                combo = q.get_nowait()
            except _queue.Empty:
                return
            try:
                board = combo["site"]
                with semaphores.get(board, fallback_sema):
                    status, _ = get_cache_entry(
                        combo["role"], combo["site"], combo.get("city", ""),
                        combo.get("state", ""), combo.get("country", ""),
                        combo["internship_mode"], combo["hours_old"],
                        ttl_hours=config.CACHE_TTL_HOURS, min_volume=config.CACHE_MIN_VOLUME,
                    )
                    if status == "fresh":
                        continue
                    where = combo.get("state") or combo.get("country") or ""
                    log(f"[PREWARM] {combo['role']} @ {combo['site']} | {where} "
                        f"({combo.get('country')}) mode={'intern' if combo['internship_mode'] else 'normal'}")
                    _scrape_combos(
                        None, [combo],
                        keywords=[], internship_mode=combo["internship_mode"],
                        hours_old=combo["hours_old"],
                        scrape_limit=config.CACHE_PREWARM_LIMIT,
                        stagger=(0, 0),
                    )
            except Exception as e:
                log(f"[PREWARM] Failed {combo.get('role')}@{combo.get('site')}: {e}")
            finally:
                if config.PREWARM_DELAY_SECONDS:
                    threading.Event().wait(config.PREWARM_DELAY_SECONDS)
                q.task_done()

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


def run_prewarm() -> int:
    """One scheduler pass: seed the queue, then warm up to
    PREWARM_MAX_COMBOS_PER_RUN stale/missing combos. Returns count warmed."""
    global _own_lock
    import config

    if not config.SCHEDULER_ENABLED:
        return 0
    if not _own_lock:
        _own_lock = _heartbeat()
        if not _own_lock:
            log("[PREWARM] Another process owns the prewarm loop — skipping this pass")
            return 0

    import db
    from db import get_cache_entry, get_prewarm_queue, seed_prewarm_queue

    seed_prewarm_queue(_grid_combos())
    db.gc_custom_prewarm()
    db.gc_sessions()
    queue = get_prewarm_queue()
    limit = config.PREWARM_MAX_COMBOS_PER_RUN
    todo = []
    for combo in queue:
        if len(todo) >= limit:
            break
        status, _ = get_cache_entry(
            combo["role"], combo["site"], combo.get("city", ""),
            combo.get("state", ""), combo.get("country", ""),
            combo["internship_mode"], combo["hours_old"],
            ttl_hours=config.CACHE_TTL_HOURS, min_volume=config.CACHE_MIN_VOLUME,
        )
        if status == "fresh":
            continue
        combo = dict(combo)
        combo["location"] = combo.get("city") or combo.get("state") or combo.get("country") or ""
        combo["indeed_country"] = _INDEED_COUNTRY.get((combo.get("country") or "").lower(), "USA")
        todo.append(combo)

    if not todo:
        log("[PREWARM] Entire queue is fresh — nothing to do this pass")
        return 0

    log(f"[PREWARM] Warming {len(todo)} combo(s) with {config.PREWARM_WORKERS} worker(s)...")
    _run_workers(todo, config)
    return len(todo)


def start_scheduler():
    """Start the background prewarm scheduler (idempotent) + one boot warm-up."""
    global _scheduler
    if _scheduler is not None:
        return
    import config

    if not config.SCHEDULER_ENABLED:
        log("[PREWARM] Scheduler disabled via SCHEDULER_ENABLED")
        return
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.interval import IntervalTrigger

    _scheduler = BackgroundScheduler(daemon=True, job_defaults={
        "coalesce": True,
        "max_instances": 1,
        "misfire_grace_time": 3600,
    })
    _scheduler.add_job(
        run_prewarm,
        IntervalTrigger(minutes=config.SCHEDULER_INTERVAL_MINUTES),
        id="prewarm",
        replace_existing=True,
    )
    _scheduler.start()
    log(f"[PREWARM] Scheduler started — runs every {config.SCHEDULER_INTERVAL_MINUTES} minutes")
    _start_heartbeat_loop()

    def _boot_warmup():
        # Retry a few times so a just-expired lock from a crashed/^C'd process
        # doesn't force us to wait for the next 180-minute interval.
        for _ in range(8):
            try:
                run_prewarm()
            except Exception as e:
                log(f"[PREWARM] Boot warm-up failed: {e}")
            if _own_lock:
                break
            threading.Event().wait(45)

    threading.Thread(target=_boot_warmup, daemon=True).start()


def shutdown_scheduler():
    """Stop the scheduler and release the prewarm lock if we own it."""
    global _scheduler, _own_lock
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:
            pass
        _scheduler = None
    if _own_lock:
        try:
            _release_lock()
        except Exception:
            pass
        _own_lock = False
        log("[PREWARM] Scheduler stopped — lock released")

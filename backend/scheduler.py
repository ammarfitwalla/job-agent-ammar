"""Feature B — self-healing prewarm scheduler.

Scrapes the prewarm_queue grid (30 roles x all states of in/us/ie/ae x boards
x both modes) in the background, capped per run by PREWARM_MAX_COMBOS_PER_RUN,
with per-board concurrency limits. Results land in the job_cache table so user
searches hit instantly.

A DB-backed leader lock keeps only one process prewarming when multiple
backend processes share the same database.
"""
import os
import gzip
import socket
import threading
from datetime import datetime, date
import tempfile

from utils.logger import log

# Seeds only: the live map is resolved lazily from countrystatecity so that every
# CACHE_COUNTRIES / CACHE_TOP_STATES code gets a real country name instead of
# silently falling back to the US site.
_INDEED_COUNTRY_SEED = {"in": "India", "us": "USA", "ie": "Ireland",
                        "ae": "united arab emirates"}
_INDEED_COUNTRY = dict(_INDEED_COUNTRY_SEED)
_indeed_country_lock = threading.Lock()


def _indeed_country_name(country_code: str) -> str:
    """Indeed's country name for an ISO2 code.

    Resolves from countrystatecity on first use and caches the whole map, so a
    country missing from CACHE_COUNTRIES still reaches the right Indeed site
    rather than defaulting to the US."""
    cc = (country_code or "").lower()
    with _indeed_country_lock:
        if len(_INDEED_COUNTRY) <= len(_INDEED_COUNTRY_SEED):
            try:
                from countrystatecity_countries import get_countries
                for c in get_countries():
                    name = (getattr(c, "name", "") or "").strip()
                    # Seeds are board-tested values ("USA", lowercase "united
                    # arab emirates"); never let a country list overwrite them.
                    if name and c.iso2.lower() not in _INDEED_COUNTRY:
                        _INDEED_COUNTRY[c.iso2.lower()] = name
            except Exception:
                pass
        return _INDEED_COUNTRY.get(cc, _INDEED_COUNTRY.get("us", "USA"))


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
                                        "indeed_country": _indeed_country_name(country),
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
                            "indeed_country": _indeed_country_name(country),
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
            "indeed_country": _indeed_country_name(country_code),
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


def _heartbeat(stale_after_seconds: float = _STALE_LOCK_SECONDS,
               table: str = "scheduler_lock") -> bool:
    """Renew/acquire the single-owner lock. Returns True if we own it."""
    from db import _get_conn

    now = datetime.utcnow().isoformat()
    with _get_conn() as (conn, cur):
        cur.execute(f"SELECT owner, last_heartbeat FROM {table} WHERE id = 1")
        row = cur.fetchone()
        if row is None:
            cur.execute(
                f"INSERT INTO {table} (id, owner, started_at, last_heartbeat) VALUES (1, ?, ?, ?)",
                (_OWNER, now, now),
            )
            conn.commit()
            return True
        if row["owner"] == _OWNER:
            cur.execute(f"UPDATE {table} SET last_heartbeat = ? WHERE id = 1", (now,))
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
                f"UPDATE {table} SET owner = ?, started_at = ?, last_heartbeat = ? WHERE id = 1",
                (_OWNER, now, now),
            )
            conn.commit()
            return True
        return False


def _release_lock(table: str = "scheduler_lock"):
    """Clear the lock row only if we are the current owner."""
    from db import _get_conn

    with _get_conn() as (conn, cur):
        cur.execute(f"DELETE FROM {table} WHERE id = 1 AND owner = ?", (_OWNER,))
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
    db.gc_job_cache(
        max_age_hours=config.CACHE_MAX_AGE_HOURS,
        max_entries=config.CACHE_MAX_ENTRIES,
    )
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
        combo["indeed_country"] = _indeed_country_name(combo.get("country") or "")
        todo.append(combo)

    if not todo:
        log("[PREWARM] Entire queue is fresh — nothing to do this pass")
        return 0

    log(f"[PREWARM] Warming {len(todo)} combo(s) with {config.PREWARM_WORKERS} worker(s)...")
    _run_workers(todo, config)
    return len(todo)


def run_db_backup():
    """Create a clean DB snapshot, gzip it, and email it."""
    import config
    try:
        from db import _DB_PATH, _get_conn
        from utils.smtp_sender import send_email_with_attachment

        backup_tmp = os.path.join(tempfile.gettempdir(), f"backup_{date.today()}.db")
        gz_tmp = backup_tmp + ".gz"

        with _get_conn() as (conn, cur):
            cur.execute(f"VACUUM INTO '{backup_tmp}'")

        with open(backup_tmp, "rb") as f_in, gzip.open(gz_tmp, "wb") as f_out:
            f_out.write(f_in.read())

        gz_size_mb = round(os.path.getsize(gz_tmp) / 1048576, 2)
        ok = send_email_with_attachment(
            to=config.DB_BACKUP_EMAIL,
            subject=f"JobAwn — DB Backup ({date.today()})",
            html_body=f"<p>Attached is the database snapshot ({gz_size_mb} MB gzipped).</p>",
            file_path=gz_tmp,
            filename=f"job_agent_{date.today()}.db.gz",
        )
        log(f"[BACKUP] {'Sent' if ok else 'FAILED'} — {gz_size_mb} MB to {config.DB_BACKUP_EMAIL}")
    except Exception as e:
        log(f"[BACKUP] Error: {e}")
    finally:
        for p in (backup_tmp, gz_tmp):
            try:
                if os.path.isfile(p):
                    os.remove(p)
            except Exception:
                pass


def enqueue_confirm_reminders():
    """Scan for accepted referrals whose confirmation cooldown has elapsed and
    enqueue a one-time reminder to each party that still hasn't confirmed.

    Fired at the top of every mail-worker pass (incl. boot) so a reminder lands
    within one interval of the 48h cooldown ending. Dedup keys
    confirm_reminder:{req_id}:receiver|sender guarantee one email per party."""
    import config
    try:
        if not config.MAIL_QUEUE_ENABLED:
            return 0
        from db import enqueue_email, get_pending_confirm_reminders
        from emails import templates

        count = 0
        for row in get_pending_confirm_reminders():
            req_id = row["id"]
            company = row.get("company") or "their company"
            if not row.get("receiver_confirmed"):
                subj, html, text, _c = templates.build_confirm_reminder_receiver(
                    row.get("to_name") or "", row.get("from_name") or "", company)
                if enqueue_email(row["to_email"], subj, html, text,
                                 dedup_key=f"confirm_reminder:{req_id}:receiver"):
                    count += 1
            if not row.get("sender_confirmed"):
                subj, html, text, _c = templates.build_confirm_reminder_sender(
                    row.get("from_name") or "", row.get("to_name") or "", company)
                if enqueue_email(row["from_email"], subj, html, text,
                                 dedup_key=f"confirm_reminder:{req_id}:sender"):
                    count += 1
        if count:
            log(f"[MAIL] Queued {count} confirmation reminder(s)")
        return count
    except Exception as e:
        log(f"[MAIL] Confirmation reminder scan error: {e}")
        return 0


# A user's free-text `position` rarely equals a cache role verbatim
# ("Software Enginner", "Ai Engineer", "Backend Developer Intern"), and
# job_cache.role is BINARY-collated, so an exact lookup misses on case alone.
# These steps resolve a profile role onto a role that actually has cached jobs.
_ROLE_QUALIFIERS = {
    "intern", "internship", "trainee", "fresher", "senior", "junior", "mid",
    "entry", "level", "representative", "rep", "graduate", "associate",
}
_ROLE_FUZZY_CUTOFF = 0.82


def _norm_role(value: str) -> str:
    """Lowercase and drop qualifier tokens ("Intern", "Senior") so near-identical
    role strings compare equal. Role-defining words are always kept."""
    import re
    text = re.sub(r"[^a-z0-9+#.]", " ", (value or "").lower()).strip()
    tokens = [t for t in text.split() if t and t not in _ROLE_QUALIFIERS]
    return " ".join(tokens) or text


def _cached_role_vocab(hours_old: int) -> tuple:
    """(lower -> canonical, [(normalized, canonical)]) for every role that has
    cache rows. Read once per pass — the vocabulary is small, so this is cheaper
    than adding an index or a schema change."""
    try:
        from db import get_cached_roles
        roles = get_cached_roles(0, hours_old, 0)
    except Exception:
        return {}, []
    exact = {r.lower(): r for r in roles}
    return exact, [(_norm_role(r), r) for r in roles]


def _resolve_role(raw: str, vocab: tuple) -> str:
    """Canonical cached role for a free-text profile role, or "" when nothing
    matches confidently. Exact -> case-insensitive -> qualifier-stripped ->
    typo/punctuation. The result is only ever a lookup key: the caller confirms
    it returns real jobs before anything is rendered, and the email always shows
    the canonical role rather than the user's spelling."""
    role = (raw or "").strip()
    if not role:
        return ""
    exact, fuzzy = vocab or ({}, [])
    hit = exact.get(role.lower())
    if hit:
        return hit
    if not fuzzy:
        return ""
    norm = _norm_role(role)
    for norm_role, canonical in fuzzy:
        if norm and norm_role == norm:
            return canonical
    try:
        import difflib
        best = difflib.get_close_matches(norm, [n for n, _ in fuzzy], n=1,
                                         cutoff=_ROLE_FUZZY_CUTOFF)
    except Exception:
        return ""
    return next((c for n, c in fuzzy if n == best[0]), "") if best else ""


def _engagement_country(user: dict) -> str:
    """ISO-2 market for the user's engagement email.

    The profile country first, then the country the app recorded on the user's
    most recent geolocated visit — as an ISO-2 code when we captured one, else
    normalized from the name ("India" -> "in"), since job_cache is keyed on the
    code and most visit rows predate the column. "" when there's no signal at
    all: we don't guess a market, so the caller has nothing to search and sends
    the generic fallback."""
    raw = (user.get("country") or "").strip()
    if raw:
        code = raw.lower()
        if len(code) > 2:
            try:
                from db import country_code_for_name
                code = country_code_for_name(raw) or code
            except Exception:
                pass
        return code
    code = (user.get("visit_country_code") or "").strip().lower()
    if code:
        return code
    name = (user.get("visit_country") or "").strip()
    if not name:
        return ""
    try:
        from db import country_code_for_name
        return country_code_for_name(name)
    except Exception:
        return ""


def _engagement_anchor(user: dict, vocab: tuple) -> tuple:
    """Anchor for a user's engagement email as (role, label, city, state, country).

    Role and location come from the profile alone: `position` resolved onto a
    cached role, plus city/state for the location label. The label is returned
    even when the role is null — that is what lets the caller send the
    location-only email to someone who told us where they are but not what they
    want. A null role means we have no cached jobs to show, so the caller sends
    the location email (no role on file) or the generic fallback."""
    country = _engagement_country(user)
    raw_role = (user.get("position") or "").strip()
    lcity = (user.get("city") or "").strip()
    lstate = (user.get("state") or "").strip()
    label = ""
    if lcity or lstate:
        # Avoid "New Delhi, Delhi" — only append the state when the city
        # doesn't already imply it.
        if lcity and lstate and lstate.lower() not in lcity.lower():
            label = f"{lcity}, {lstate}"
        else:
            label = lcity or lstate
    role = _resolve_role(raw_role, vocab)
    if not role or not country:
        return None, label, lcity, lstate, country
    return role, label, lcity, lstate, country


def _cache_jobs_for(role: str, city: str, state: str, country: str,
                    hours_old: int, max_jobs: int) -> list[dict]:
    """Merge cached jobs for one anchor scope across the active boards. Pure
    cache reads — never triggers a scrape. [] when the cache has nothing."""
    try:
        import config
        from db import get_cached_jobs_aggregate
    except Exception:
        return []
    try:
        sites = config.CACHE_SITES_INDIA if country == "in" else config.CACHE_SITES_DEFAULT
    except Exception:
        sites = []
    merged, seen = [], set()
    for site in sites:
        try:
            _status, entry = get_cached_jobs_aggregate(
                role, site, city, state, country, 0, int(hours_old),
                ttl_hours=12.0, min_volume=1, max_jobs=int(max_jobs), is_remote=0,
            )
            for j in (entry or {}).get("jobs", []) or []:
                url = j.get("url") or f"{j.get('title')}{j.get('company')}"
                if not url or url in seen:
                    continue
                seen.add(url)
                merged.append(j)
                if len(merged) >= int(max_jobs):
                    return merged
        except Exception:
            continue
    return merged


def _engagement_fresh_jobs(anchor: tuple, hours_old: int, max_jobs: int) -> tuple:
    """(jobs, label) for an anchor.

    Scopes are tried tightest-first — city leaf, then state (which unions the
    state row with its city rows), then country — and the label names only the
    scope the jobs actually came from. A location is therefore never claimed for
    a scope that had no cache, and the country rung carries no location at all.
    """
    role, label, city, state, country = anchor
    if not role:
        return [], ""
    scopes = []
    if city:
        scopes.append((city, state, label or city or state))
    if state:
        scopes.append(("", state, state))
    scopes.append(("", "", ""))
    for sc_city, sc_state, sc_label in scopes:
        jobs = _cache_jobs_for(role, sc_city, sc_state, country, hours_old, max_jobs)
        if jobs:
            return jobs, sc_label
    return [], ""


def enqueue_engagement_emails():
    """Weekly re-engagement producer: enqueue one 'come back to the app' email
    per dormant user per week.

    Fired at the top of every mail-worker pass (incl. boot), mirroring
    enqueue_confirm_reminders. Each pass processes a bounded slice
    (ENGAGEMENT_MAX_PER_RUN) of the most dormant users; the
    engage:{YYYY-WW}:{email} dedup key guarantees exactly one email per user
    within the week."""
    import config
    try:
        enabled = bool(getattr(config, "ENGAGEMENT_ENABLED", False)) and config.MAIL_QUEUE_ENABLED
        if not enabled:
            return 0
        from db import get_engagement_recipients, enqueue_email
        from emails import templates
        from emails.unsubscribe import build_unsubscribe_url
        import datetime as dt

        dormant_days = int(getattr(config, "ENGAGEMENT_DORMANT_DAYS", 7))
        min_age_days = int(getattr(config, "ENGAGEMENT_MIN_AGE_DAYS", 3))
        limit = int(getattr(config, "ENGAGEMENT_MAX_PER_RUN", 20))
        hours_old = int(getattr(config, "ENGAGEMENT_CACHE_HOURS_OLD", 168))
        max_jobs = int(getattr(config, "ENGAGEMENT_MAX_JOBS", 30))
        cutoff = (dt.datetime.utcnow() - dt.timedelta(days=dormant_days)).isoformat()
        week_key = dt.datetime.utcnow().strftime("%Y-W%W")
        vocab = _cached_role_vocab(hours_old)

        count = 0
        for user in get_engagement_recipients(cutoff, min_age_days, limit, week_key):
            email = (user.get("email") or "").strip()
            if not email:
                continue
            dedup_key = f"engage:{week_key}:{email}"
            anchor = _engagement_anchor(user, vocab)
            role, label = anchor[0], anchor[1]
            jobs, loc = ([], "") if role is None else _engagement_fresh_jobs(
                anchor, hours_old, max_jobs)
            unsub = build_unsubscribe_url(email)
            has_resume = bool(user.get("resume_filename"))
            # Which of the three emails: a role with cached jobs (labelled with
            # the scope the jobs actually came from), else a user who told us a
            # location but no role, else the strictly generic nudge. A role with
            # nothing cached falls to the generic one on purpose — we would
            # otherwise be inviting them to a search we have no data for.
            has_role = bool((user.get("position") or "").strip())
            if jobs:
                subj, html, text, _c = templates.build_engagement(
                    user.get("name") or "", jobs, role, loc, len(jobs),
                    has_resume, unsub)
            elif label and not has_role:
                subj, html, text, _c = templates.build_engagement_location_prompt(
                    user.get("name") or "", label, has_resume, unsub)
            else:
                subj, html, text, _c = templates.build_engagement_fallback(
                    user.get("name") or "", has_resume, unsub)
            if enqueue_email(email, subj, html, text, dedup_key=dedup_key):
                count += 1
        if count:
            log(f"[MAIL] Queued {count} engagement email(s)")
        return count
    except Exception as e:
        log(f"[MAIL] Engagement scan error: {e}")
        return 0


def run_mail_queue():
    """Drain the transactional email queue: send pending mails, mark sent/failed.

    Controlled by the dedicated mail worker (start_mail_worker), which runs
    every MAIL_QUEUE_INTERVAL_MINUTES — independent of SCHEDULER_ENABLED so the
    queue still drains in environments where the prewarm scheduler is off.
    Sends up to MAIL_QUEUE_MAX_PER_RUN per pass; each email gets up to 3
    attempts before being marked failed."""
    import config
    try:
        if not config.MAIL_QUEUE_ENABLED:
            return 0
        enqueue_confirm_reminders()
        enqueue_engagement_emails()
        from db import get_pending_emails, mark_email_sent, mark_email_failed
        from utils.smtp_sender import send_email

        sent = 0
        pending = get_pending_emails(config.MAIL_QUEUE_MAX_PER_RUN)
        for row in pending:
            try:
                ok = send_email(row["recipient"], row["subject"],
                                row["html_body"], row["text_body"] or None)
            except Exception as e:
                ok = False
                log(f"[MAIL] Error sending #{row['id']} to {row['recipient']}: {e}")
            if ok:
                mark_email_sent(row["id"])
                sent += 1
            else:
                mark_email_failed(row["id"], f"Sending failed for to={row['recipient']}")
        if sent:
            log(f"[MAIL] Queue drained — sent {sent} of {len(pending)}")
        return sent
    except Exception as e:
        log(f"[MAIL] Queue drain error: {e}")
        return 0


_mail_thread = None
_mail_stop = threading.Event()


def _mail_loop():
    import config
    while not _mail_stop.wait(config.MAIL_QUEUE_INTERVAL_MINUTES * 60):
        try:
            run_mail_queue()
        except Exception as e:
            log(f"[MAIL] Worker pass error: {e}")


def start_mail_worker():
    """Start the transactional-mail drain loop (idempotent, daemon thread).

    Not tied to SCHEDULER_ENABLED — mail delivery is time-sensitive (~5 min)
    and must keep working even when the heavy prewarm scheduler is off."""
    global _mail_thread
    if _mail_thread is not None and _mail_thread.is_alive():
        return
    import config
    if not config.MAIL_QUEUE_ENABLED:
        log("[MAIL] Mail queue disabled via MAIL_QUEUE_ENABLED")
        return
    _mail_stop.clear()
    try:
        run_mail_queue()
    except Exception:
        pass
    _mail_thread = threading.Thread(target=_mail_loop, daemon=True, name="mail-queue")
    _mail_thread.start()
    log(f"[MAIL] Worker started — draining every {config.MAIL_QUEUE_INTERVAL_MINUTES} min")


def stop_mail_worker():
    global _mail_thread
    _mail_stop.set()
    if _mail_thread is not None:
        _mail_thread.join(timeout=5)
        _mail_thread = None


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
    _scheduler.add_job(
        run_db_backup,
        IntervalTrigger(hours=48),
        id="db_backup",
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

    def _boot_backup():
        threading.Event().wait(30)
        try:
            run_db_backup()
        except Exception as e:
            log(f"[BACKUP] Boot backup failed: {e}")

    threading.Thread(target=_boot_backup, daemon=True).start()


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


# ── Proxy pool refresher (always-on) ──────────────────────────────
#
# Runs independent of SCHEDULER_ENABLED so a warm pool exists even with the
# prewarm scheduler off. Uses its own leader lock (proxy_refresh_lock) so an
# active prewarm owner can never strangle proxy refreshes.

_PROXY_TESTERS = {}
_PROXY_REFRESH_THREAD = None
_PROXY_REFRESH_STOP = None


def _register_proxy_testers():
    if _PROXY_TESTERS:
        return
    try:
        from scrapers import naukri_scraper
        _PROXY_TESTERS["naukri"] = naukri_scraper._proxy_test_naukri
        log(f"[PROXY-POOL] registered testers: {list(_PROXY_TESTERS)}")
    except Exception as e:
        log(f"[PROXY-POOL] tester registration failed: {e}")


def _probe_with_timeout(tester, proxy_url: str, timeout: float = 5.0) -> str:
    """Probe a proxy but bail out after `timeout` seconds.

    tls-client's `timeout_seconds` doesn't reliably bound connect/TLS-handshake
    on hostile proxies, and a single hung probe used to freeze the whole pool
    refresher. A daemon thread + bounded join keeps the pass moving; a hung
    probe thread is simply abandoned (isolated, holds no locks).

    Returns "ok" (probe succeeded), "fail" (clean rejection), or "timeout"
    (still running when the deadline hit → treated as unusable)."""
    result = {}

    def _run():
        try:
            result["ok"] = bool(tester(proxy_url))
        except Exception:
            result["ok"] = False

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        return "timeout"
    return "ok" if result.get("ok", False) else "fail"


def refresh_proxy_pool(board: str = "naukri") -> int:
    """One refresh pass: probe free proxies for `board`, upsert working ones.

    Single-owner via the proxy_refresh_lock leader pattern. Returns -1 if we
    don't own the lock, else the number of working proxies found. Pass is
    time-bounded per probe and ends early once we have enough working proxies,
    so it can never hang the pool indefinitely."""
    import config
    from db import (refresh_pool, upsert_proxy, proxy_pool_stats)

    if not _heartbeat(table="proxy_refresh_lock"):
        return -1
    try:
        _register_proxy_testers()
        tester = _PROXY_TESTERS.get(board)
        if tester is None:
            log(f"[PROXY-POOL] no tester for board {board}")
            return 0
        from scrapers.naukri_scraper import _fetch_free_proxies
        all_proxies = _fetch_free_proxies()
        if not all_proxies:
            log(f"[PROXY-POOL] {board}: no proxies fetched")
            return 0

        test_limit = getattr(config, "NAUKRI_PROXY_TEST_LIMIT", 30)
        pool_max = getattr(config, "NAUKRI_PROXY_POOL_MAX", 50)
        min_target = getattr(config, "NAUKRI_PROXY_TEST_MIN_TARGET", 10)
        probe_timeout = getattr(config, "NAUKRI_PROXY_TEST_TIMEOUT", 5) + 3  # hard cap

        tested = 0
        working = 0
        timed_out = 0
        failed = 0
        for p in all_proxies:
            if tested >= test_limit or working >= min_target:
                break
            proxy_url = p if p.startswith("http") else f"http://{p}"
            tested += 1
            status = _probe_with_timeout(tester, proxy_url, probe_timeout)
            if status == "timeout":
                timed_out += 1
                continue
            if status != "ok":
                failed += 1
                continue
            upsert_proxy(board, proxy_url, rekindle=True)
            working += 1

        refresh_pool(board, pool_max)
        stats = proxy_pool_stats(board)
        log(f"[PROXY-POOL] {board}: refresh {working}/{tested} working "
            f"({failed} failed, {timed_out} timed out) — "
            f"pool={stats['free']} free, {stats['in_use']} in_use, "
            f"{stats['dead']} dead")
        return working
    except Exception as e:
        log(f"[PROXY-POOL] {board}: refresh failed: {e}")
        return 0
    finally:
        try:
            _release_lock(table="proxy_refresh_lock")
        except Exception:
            pass


def _proxy_refresher_loop():
    import config
    import time

    first_delay = getattr(config, "NAUKRI_PROXY_REFRESH_MINUTES", 15) * 60
    time.sleep(max(5, min(first_delay, 60)))  # first pass ~1 min after boot
    while True:
        if _PROXY_REFRESH_STOP is not None and _PROXY_REFRESH_STOP.is_set():
            break
        refresh_proxy_pool("naukri")
        if _PROXY_REFRESH_STOP is not None and _PROXY_REFRESH_STOP.wait(first_delay):
            break


def start_proxy_refresher():
    """Start the always-on proxy pool refresher (idempotent). Gated only on
    NAUKRI_USE_PROXY — NOT on SCHEDULER_ENABLED."""
    global _PROXY_REFRESH_THREAD, _PROXY_REFRESH_STOP
    if _PROXY_REFRESH_THREAD is not None:
        return
    try:
        import config
        if not config.NAUKRI_USE_PROXY:
            log("[PROXY-POOL] disabled via NAUKRI_USE_PROXY=False")
            return
    except Exception:
        pass
    _PROXY_REFRESH_STOP = threading.Event()
    t = threading.Thread(target=_proxy_refresher_loop, daemon=True,
                         name="proxy-refresher")
    t.start()
    _PROXY_REFRESH_THREAD = t
    log("[PROXY-POOL] always-on refresher started")


def stop_proxy_refresher():
    global _PROXY_REFRESH_THREAD, _PROXY_REFRESH_STOP
    if _PROXY_REFRESH_STOP is not None:
        _PROXY_REFRESH_STOP.set()
        _PROXY_REFRESH_THREAD = None
        _PROXY_REFRESH_STOP = None

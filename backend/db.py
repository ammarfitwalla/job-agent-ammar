import sqlite3
import os
import json
import threading
import time
import contextlib
from datetime import datetime, timedelta
from typing import Optional

_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "job_agent.db")
_write_lock = threading.Lock()
_job_count_cache: dict[str, int] = {}
DEV_MODE = False


@contextlib.contextmanager
def _get_conn():
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    try:
        yield conn, conn.cursor()
    finally:
        conn.close()


def init_db():
    with _get_conn() as (conn, cur):
        cur.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                status TEXT DEFAULT 'idle',
                internship_mode INTEGER DEFAULT 0,
                pass_num INTEGER DEFAULT 0,
                max_passes INTEGER DEFAULT 0,
                filtered_gen INTEGER DEFAULT 0,
                cancel INTEGER DEFAULT 0,
                queue_position INTEGER DEFAULT 0,
                sites TEXT DEFAULT '[]',
                keywords TEXT DEFAULT '[]',
                roles TEXT DEFAULT '[]',
                keywords_count INTEGER DEFAULT 0,
                roles_count INTEGER DEFAULT 0,
            resume_length INTEGER DEFAULT 0,
            scraped INTEGER DEFAULT 0,
            elapsed_seconds REAL DEFAULT 0,
            location TEXT DEFAULT ''
        );
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                title TEXT NOT NULL,
                company TEXT DEFAULT '',
                location TEXT DEFAULT '',
                url TEXT DEFAULT '',
                description TEXT DEFAULT '',
                tags TEXT DEFAULT '[]',
                ai_score INTEGER,
                keyword_score INTEGER,
                total_score INTEGER,
                reason TEXT DEFAULT '',
                salary TEXT DEFAULT '',
                experience_level TEXT,
                is_raw INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                event TEXT NOT NULL,
                data TEXT DEFAULT '{}',
                elapsed_seconds INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            );
            CREATE TABLE IF NOT EXISTS leads (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id      TEXT,
                email           TEXT NOT NULL,
                name            TEXT DEFAULT '',
                roles           TEXT DEFAULT '[]',
                location        TEXT DEFAULT '',
                keywords        TEXT DEFAULT '[]',
                internship_mode INTEGER DEFAULT 0,
                resume_snippet  TEXT DEFAULT '',
                source          TEXT DEFAULT 'web',
                created_at      TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS users (
                email TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                company TEXT DEFAULT '',
                position TEXT DEFAULT '',
                linkedin_url TEXT DEFAULT '',
                resume_filename TEXT DEFAULT '',
                referral_credits INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS verification_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL,
                code TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                used INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_vcodes_email ON verification_codes(email);
            CREATE TABLE IF NOT EXISTS visits (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                visit_id        TEXT NOT NULL UNIQUE,
                ip_address      TEXT NOT NULL,
                user_agent      TEXT DEFAULT '',
                device_type     TEXT DEFAULT 'unknown',
                referer         TEXT DEFAULT '',
                path            TEXT DEFAULT '/',
                session_id      TEXT DEFAULT '',
                user_email      TEXT DEFAULT '',
                duration_seconds REAL DEFAULT 0,
                heartbeats      INTEGER DEFAULT 0,
                country         TEXT DEFAULT '',
                city            TEXT DEFAULT '',
                region          TEXT DEFAULT '',
                created_at      TEXT NOT NULL,
                last_heartbeat  TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_visits_ip ON visits(ip_address);
            CREATE TABLE IF NOT EXISTS saved_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_email TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                company TEXT DEFAULT '',
                url TEXT DEFAULT '',
                location TEXT DEFAULT '',
                salary TEXT DEFAULT '',
                total_score INTEGER DEFAULT 0,
                ai_score INTEGER DEFAULT 0,
                keyword_score INTEGER DEFAULT 0,
                reason TEXT DEFAULT '',
                experience_level TEXT DEFAULT '',
                tags TEXT DEFAULT '[]',
                site TEXT DEFAULT '',
                application_status TEXT DEFAULT 'saved',
                saved_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_email) REFERENCES users(email),
                UNIQUE(user_email, url)
            );
            CREATE INDEX IF NOT EXISTS idx_saved_email ON saved_jobs(user_email);
            CREATE INDEX IF NOT EXISTS idx_saved_status ON saved_jobs(user_email, application_status);
            CREATE TABLE IF NOT EXISTS saved_searches (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL,
                name TEXT DEFAULT '',
                sites TEXT DEFAULT '[]',
                keywords TEXT DEFAULT '[]',
                roles TEXT DEFAULT '[]',
                location TEXT DEFAULT '',
                internship_mode INTEGER DEFAULT 0,
                interval_hours INTEGER DEFAULT 168,
                last_run_at TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (email) REFERENCES users(email)
            );
            CREATE INDEX IF NOT EXISTS idx_saved_search_email ON saved_searches(email);
            CREATE INDEX IF NOT EXISTS idx_jobs_session ON jobs(session_id);
            CREATE INDEX IF NOT EXISTS idx_jobs_raw ON jobs(session_id, is_raw);
            CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);
            CREATE TABLE IF NOT EXISTS referral_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_email TEXT NOT NULL,
                to_email TEXT NOT NULL,
                job_url TEXT DEFAULT '',
                job_title TEXT DEFAULT '',
                company TEXT DEFAULT '',
                match_score INTEGER DEFAULT 0,
                message TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                credit_awarded INTEGER DEFAULT 0,
                accepted_at TEXT DEFAULT '',
                receiver_confirmed INTEGER DEFAULT 0,
                sender_confirmed INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS custom_companies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_ref_req_from ON referral_requests(from_email);
            CREATE INDEX IF NOT EXISTS idx_ref_req_to ON referral_requests(to_email, status);
        """)
        # Migrate existing visits table — add location columns if missing
        for col in ("country", "city", "region"):
            try:
                cur.execute(f"ALTER TABLE visits ADD COLUMN {col} TEXT DEFAULT ''")
            except Exception:
                pass
        # Migrate existing users table — add employment columns if missing
        for col in ("company TEXT DEFAULT ''", "position TEXT DEFAULT ''", "linkedin_url TEXT DEFAULT ''", "referral_credits INTEGER DEFAULT 0"):
            try:
                cur.execute(f"ALTER TABLE users ADD COLUMN {col}")
            except Exception:
                pass
        # Migrate existing referral_requests table
        try:
            cur.execute("ALTER TABLE referral_requests ADD COLUMN credit_awarded INTEGER DEFAULT 0")
        except Exception:
            pass
        # Migrate existing users table — add resume_filename
        try:
            cur.execute("ALTER TABLE users ADD COLUMN resume_filename TEXT DEFAULT ''")
        except Exception:
            pass
        # Migrate existing referral_requests table — add dual-confirmation columns
        for col in ("accepted_at TEXT DEFAULT ''", "receiver_confirmed INTEGER DEFAULT 0", "sender_confirmed INTEGER DEFAULT 0"):
            try:
                cur.execute(f"ALTER TABLE referral_requests ADD COLUMN {col}")
            except Exception:
                pass
        conn.commit()
        try:
            cur.execute("ALTER TABLE sessions ADD COLUMN elapsed_seconds REAL DEFAULT 0")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE sessions ADD COLUMN keywords TEXT DEFAULT '[]'")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE sessions ADD COLUMN roles TEXT DEFAULT '[]'")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE sessions ADD COLUMN location TEXT DEFAULT ''")
        except Exception:
            pass


def gc_sessions(max_age_minutes: int = 240):
    with _write_lock:
        with _get_conn() as (conn, cur):
            cutoff = (datetime.utcnow() - timedelta(minutes=max_age_minutes)).isoformat()
            cur.execute("DELETE FROM sessions WHERE updated_at < ?", (cutoff,))
            cur.execute("DELETE FROM jobs WHERE session_id NOT IN (SELECT id FROM sessions)")
            cur.execute("DELETE FROM events WHERE session_id NOT IN (SELECT id FROM sessions)")
            conn.commit()


def _now():
    return datetime.utcnow().isoformat()


# ── Sessions ──

def create_session(sid: str, **kwargs):
    with _write_lock:
        with _get_conn() as (conn, cur):
            now = _now()
            fields = {
                "id": sid, "created_at": now, "updated_at": now,
                "sites": json.dumps(kwargs.get("sites", [])),
                "keywords": json.dumps(kwargs.get("keywords", [])),
                "roles": json.dumps(kwargs.get("roles", [])),
                "keywords_count": kwargs.get("keywords_count", 0),
                "roles_count": kwargs.get("roles_count", 0),
                "resume_length": kwargs.get("resume_length", 0),
                "internship_mode": 1 if kwargs.get("internship_mode") else 0,
                "location": kwargs.get("location", ""),
            }
            cur.execute("""INSERT OR REPLACE INTO sessions
                (id, created_at, updated_at, sites, keywords, roles, keywords_count, roles_count, resume_length, internship_mode, location)
                VALUES (:id, :created_at, :updated_at, :sites, :keywords, :roles, :keywords_count, :roles_count, :resume_length, :internship_mode, :location)""", fields)
            conn.commit()


def update_session(sid: str, **kwargs):
    with _write_lock:
        with _get_conn() as (conn, cur):
            allowed = {"status", "pass_num", "max_passes", "filtered_gen", "cancel", "queue_position", "scraped", "elapsed_seconds"}
            updates = {k: v for k, v in kwargs.items() if k in allowed}
            if not updates:
                return
            updates["updated_at"] = _now()
            set_clause = ", ".join(f"{k} = :{k}" for k in updates)
            updates["id"] = sid
            cur.execute(f"UPDATE sessions SET {set_clause} WHERE id = :id", updates)
            conn.commit()


def get_session(sid: str) -> Optional[dict]:
    with _get_conn() as (conn, cur):
        cur.execute("SELECT * FROM sessions WHERE id = ?", (sid,))
        row = cur.fetchone()
        if row is None:
            return None
        d = dict(row)
        d["internship_mode"] = bool(d["internship_mode"])
        d["cancel"] = bool(d["cancel"])
        for field in ("sites", "keywords", "roles"):
            try:
                d[field] = json.loads(d[field])
            except (json.JSONDecodeError, TypeError):
                d[field] = []
        return d


# ── Jobs ──

def _job_to_row(sid: str, job: dict) -> dict:
    return {
        "session_id": sid,
        "title": job.get("title", ""),
        "company": job.get("company", ""),
        "location": job.get("location", ""),
        "url": job.get("url", ""),
        "description": job.get("description", ""),
        "tags": json.dumps(job.get("tags", [])),
        "ai_score": job.get("ai_score"),
        "keyword_score": job.get("keyword_score"),
        "total_score": job.get("total_score"),
        "reason": job.get("reason", ""),
        "salary": job.get("salary"),
        "experience_level": job.get("experience_level"),
        "is_raw": 0,
        "created_at": _now(),
    }


def set_filtered_jobs(sid: str, jobs: list):
    with _write_lock:
        with _get_conn() as (conn, cur):
            cur.execute("DELETE FROM jobs WHERE session_id = ? AND is_raw = 0", (sid,))
            rows = [_job_to_row(sid, j) for j in jobs]
            if rows:
                cur.executemany("""INSERT INTO jobs
                    (session_id, title, company, location, url, description, tags, ai_score, keyword_score, total_score, reason, salary, experience_level, is_raw, created_at)
                    VALUES (:session_id, :title, :company, :location, :url, :description, :tags, :ai_score, :keyword_score, :total_score, :reason, :salary, :experience_level, :is_raw, :created_at)""", rows)
            conn.commit()
            _job_count_cache.pop(sid, None)


def add_filtered_job(sid: str, job: dict):
    with _write_lock:
        with _get_conn() as (conn, cur):
            row = _job_to_row(sid, job)
            cur.execute("""INSERT INTO jobs
                (session_id, title, company, location, url, description, tags, ai_score, keyword_score, total_score, reason, salary, experience_level, is_raw, created_at)
                VALUES (:session_id, :title, :company, :location, :url, :description, :tags, :ai_score, :keyword_score, :total_score, :reason, :salary, :experience_level, :is_raw, :created_at)""", row)
            conn.commit()
            _job_count_cache.pop(sid, None)


def count_filtered_jobs(sid: str) -> int:
    if sid in _job_count_cache:
        return _job_count_cache[sid]
    with _get_conn() as (conn, cur):
        cur.execute("SELECT COUNT(*) FROM jobs WHERE session_id = ? AND is_raw = 0", (sid,))
        count = cur.fetchone()[0]
        _job_count_cache[sid] = count
        return count


def get_filtered_jobs(sid: str, min_score: int = 0, site: str = "", experience_level: str = "") -> list:
    with _get_conn() as (conn, cur):
        clauses = ["session_id = ?", "is_raw = 0"]
        params = [sid]
        if min_score:
            clauses.append("COALESCE(total_score, 0) >= ?")
            params.append(min_score)
        if site:
            clauses.append("LOWER(url) LIKE ?")
            params.append(f"%{site.lower()}%")
        if experience_level:
            clauses.append("experience_level = ?")
            params.append(experience_level)
        query = f"SELECT * FROM jobs WHERE {' AND '.join(clauses)} ORDER BY COALESCE(total_score, 0) DESC"
        cur.execute(query, params)
        rows = cur.fetchall()
        jobs = []
        for row in rows:
            d = dict(row)
            try:
                d["tags"] = json.loads(d["tags"])
            except (json.JSONDecodeError, TypeError):
                d["tags"] = []
            del d["id"]
            del d["session_id"]
            del d["is_raw"]
            del d["created_at"]
            jobs.append(d)
        return jobs


# ── Events ──

def add_event(sid: str, event: str, data: dict = None, elapsed: int = 0):
    with _write_lock:
        with _get_conn() as (conn, cur):
            cur.execute("""INSERT INTO events (session_id, event, data, elapsed_seconds, created_at)
                VALUES (?, ?, ?, ?, ?)""", (sid, event, json.dumps(data or {}), elapsed, _now()))
            conn.commit()

def get_events(sid: str, limit: int = 50) -> list[dict]:
    with _get_conn() as (conn, cur):
        cur.execute(
            "SELECT event, elapsed_seconds, created_at FROM events WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (sid, limit),
        )
        rows = cur.fetchall()
        return [{"event": row[0], "elapsed_seconds": row[1] or 0, "created_at": row[2]} for row in rows][::-1]


# ── Leads ──

def add_lead(
    session_id: str = None,
    email: str = "",
    name: str = "",
    roles: list = None,
    location: str = "",
    keywords: list = None,
    internship_mode: bool = False,
    resume_snippet: str = "",
    source: str = "web",
) -> int:
    with _write_lock:
        with _get_conn() as (conn, cur):
            cur.execute("""INSERT INTO leads
                (session_id, email, name, roles, location, keywords, internship_mode, resume_snippet, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
                    session_id, email, name,
                    json.dumps(roles or []),
                    location,
                    json.dumps(keywords or []),
                    1 if internship_mode else 0,
                    resume_snippet, source, _now(),
                ))
            conn.commit()
            lead_id = cur.lastrowid
    elapsed = 0
    if session_id:
        s = get_session(session_id)
        if s and s.get("created_at"):
            elapsed = int((datetime.utcnow() - datetime.fromisoformat(s["created_at"])).total_seconds())
    add_event(session_id or "", "lead_captured", {"email": email, "has_name": bool(name), "lead_id": lead_id}, elapsed)
    return lead_id


def get_leads(limit: int = 100) -> list[dict]:
    with _get_conn() as (conn, cur):
        cur.execute("SELECT * FROM leads ORDER BY created_at DESC LIMIT ?", (limit,))
        rows = cur.fetchall()
        results = []
        for row in rows:
            d = dict(row)
            try:
                d["roles"] = json.loads(d["roles"])
            except (json.JSONDecodeError, TypeError):
                d["roles"] = []
            try:
                d["keywords"] = json.loads(d["keywords"])
            except (json.JSONDecodeError, TypeError):
                d["keywords"] = []
            results.append(d)
        return results


# ── Users ──

def get_user(email: str) -> Optional[dict]:
    with _get_conn() as (conn, cur):
        cur.execute("SELECT * FROM users WHERE email = ?", (email,))
        row = cur.fetchone()
        return dict(row) if row else None


def get_all_users(limit: int = 500) -> list[dict]:
    with _get_conn() as (conn, cur):
        cur.execute("SELECT u.* FROM users u ORDER BY u.created_at DESC LIMIT ?", (limit,))
        return [dict(r) for r in cur.fetchall()]


def create_user(email: str, name: str, company: str = "", position: str = "", linkedin_url: str = "") -> dict:
    now = _now()
    with _write_lock:
        with _get_conn() as (conn, cur):
            cur.execute(
                "INSERT OR IGNORE INTO users (email, name, company, position, linkedin_url, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (email, name, company, position, linkedin_url, now, now))
            conn.commit()
    return {"email": email, "name": name, "company": company, "position": position, "linkedin_url": linkedin_url, "referral_credits": 0, "created_at": now}


def update_user_name(email: str, name: str):
    with _write_lock:
        with _get_conn() as (conn, cur):
            cur.execute("UPDATE users SET name = ?, updated_at = ? WHERE email = ?",
                         (name, _now(), email))
            conn.commit()

def update_user_profile(email: str, name: str = None, company: str = None, position: str = None, linkedin_url: str = None, resume_filename: str = None):
    fields = []
    values = []
    if name is not None:
        fields.append("name = ?")
        values.append(name)
    if company is not None:
        fields.append("company = ?")
        values.append(company)
    if position is not None:
        fields.append("position = ?")
        values.append(position)
    if linkedin_url is not None:
        fields.append("linkedin_url = ?")
        values.append(linkedin_url)
    if resume_filename is not None:
        fields.append("resume_filename = ?")
        values.append(resume_filename)
    if not fields:
        return
    fields.append("updated_at = ?")
    values.append(_now())
    values.append(email)
    with _write_lock:
        with _get_conn() as (conn, cur):
            cur.execute(f"UPDATE users SET {', '.join(fields)} WHERE email = ?", values)
            conn.commit()

def get_users_by_company(company: str) -> list[dict]:
    with _get_conn() as (conn, cur):
        cur.execute("SELECT email, name, position, linkedin_url FROM users WHERE LOWER(company) = LOWER(?)", (company,))
        return [dict(r) for r in cur.fetchall()]


def get_company_user_counts(companies: list[str], exclude_email: str = None) -> dict[str, int]:
    """Returns dict of {lowercased_company: user_count}, optionally excluding a user."""
    if not companies:
        return {}
    with _get_conn() as (conn, cur):
        params = [c.lower() for c in companies]
        placeholders = ",".join("?" * len(params))
        query = f"SELECT LOWER(company), COUNT(*) FROM users WHERE LOWER(company) IN ({placeholders}) AND company != ''"
        if exclude_email:
            query += " AND email != ?"
            params.append(exclude_email)
        query += " GROUP BY LOWER(company)"
        cur.execute(query, params)
        return dict(cur.fetchall())


# ── Verification Codes ──

def save_verification_code(email: str, code: str, expires_at: str):
    with _write_lock:
        with _get_conn() as (conn, cur):
            cur.execute("INSERT INTO verification_codes (email, code, expires_at, used, created_at) VALUES (?, ?, ?, 0, ?)",
                         (email, code, expires_at, _now()))
            conn.commit()


def verify_code(email: str, code: str) -> bool:
    with _write_lock:
        with _get_conn() as (conn, cur):
            cur.execute(
                "SELECT id FROM verification_codes WHERE email = ? AND code = ? AND used = 0 AND expires_at > ? ORDER BY id DESC LIMIT 1",
                (email, code, _now()),
            )
            row = cur.fetchone()
            if row is None:
                return False
            cur.execute("UPDATE verification_codes SET used = 1 WHERE id = ?", (row["id"],))
            conn.commit()
            return True


# ── Saved Jobs ──

def add_saved_job(user_email: str, job: dict) -> dict:
    now = _now()
    tags = job.get("tags")
    with _write_lock:
        with _get_conn() as (conn, cur):
            cur.execute("""INSERT OR IGNORE INTO saved_jobs
                (user_email, title, company, url, location, salary, total_score, ai_score, keyword_score, reason, experience_level, tags, site, application_status, saved_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'saved', ?, ?)""", (
                    user_email,
                    job.get("title", ""),
                    job.get("company", ""),
                    job.get("url", ""),
                    job.get("location", ""),
                    job.get("salary", ""),
                    job.get("total_score", 0),
                    job.get("ai_score", 0),
                    job.get("keyword_score", 0),
                    job.get("reason", ""),
                    job.get("experience_level", ""),
                    json.dumps(tags) if isinstance(tags, list) else "[]",
                    job.get("site", ""),
                    now,
                    now,
                ))
            conn.commit()
            ok = cur.rowcount > 0
            if not ok:
                cur.execute("SELECT id FROM saved_jobs WHERE user_email = ? AND url = ?", (user_email, job.get("url", "")))
                row = cur.fetchone()
                row_id = row["id"] if row else 0
            else:
                row_id = cur.lastrowid
    return {"id": row_id, "saved": True}


def is_job_saved(user_email: str, url: str) -> bool:
    with _get_conn() as (conn, cur):
        cur.execute("SELECT 1 FROM saved_jobs WHERE user_email = ? AND url = ?", (user_email, url))
        return cur.fetchone() is not None


def batch_check_saved(user_email: str, urls: list[str]) -> dict[str, int]:
    if not user_email or not urls:
        return {}
    with _get_conn() as (conn, cur):
        placeholders = ",".join("?" for _ in urls)
        cur.execute(
            f"SELECT id, url FROM saved_jobs WHERE user_email = ? AND url IN ({placeholders})",
            [user_email] + urls,
        )
        return {row["url"]: row["id"] for row in cur.fetchall()}


def get_saved_jobs(user_email: str, status: str = "") -> list[dict]:
    with _get_conn() as (conn, cur):
        if status:
            cur.execute("SELECT * FROM saved_jobs WHERE user_email = ? AND application_status = ? ORDER BY saved_at DESC",
                         (user_email, status))
        else:
            cur.execute("SELECT * FROM saved_jobs WHERE user_email = ? ORDER BY saved_at DESC", (user_email,))
        rows = cur.fetchall()
        results = []
        for row in rows:
            d = dict(row)
            try:
                d["tags"] = json.loads(d["tags"])
            except (json.JSONDecodeError, TypeError):
                d["tags"] = []
            results.append(d)
        return results


def update_saved_job_status(job_id: int, status: str) -> bool:
    with _write_lock:
        with _get_conn() as (conn, cur):
            cur.execute("UPDATE saved_jobs SET application_status = ?, updated_at = ? WHERE id = ?",
                         (status, _now(), job_id))
            conn.commit()
            return cur.rowcount > 0


def delete_saved_job(job_id: int) -> bool:
    with _write_lock:
        with _get_conn() as (conn, cur):
            cur.execute("DELETE FROM saved_jobs WHERE id = ?", (job_id,))
            conn.commit()
            return cur.rowcount > 0


def get_saved_jobs_status_counts(user_email: str) -> dict[str, int]:
    with _get_conn() as (conn, cur):
        cur.execute(
            "SELECT application_status, COUNT(*) as cnt FROM saved_jobs WHERE user_email = ? GROUP BY application_status",
            (user_email,),
        )
        counts = {"saved": 0, "applied": 0, "interviewing": 0, "offer": 0, "rejected": 0, "total": 0}
        for row in cur.fetchall():
            s = row["application_status"]
            c = row["cnt"]
            if s in counts:
                counts[s] = c
            counts["total"] += c
        return counts


# ── Saved Searches (placeholder for future cron) ──

def add_saved_search(sid: str, email: str, name: str, sites: list, keywords: list, roles: list,
                     location: str = "", internship_mode: bool = False, interval_hours: int = 168):
    with _write_lock:
        with _get_conn() as (conn, cur):
            cur.execute("""INSERT OR REPLACE INTO saved_searches
                (id, email, name, sites, keywords, roles, location, internship_mode, interval_hours, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
                    sid, email, name,
                    json.dumps(sites), json.dumps(keywords), json.dumps(roles),
                    location, 1 if internship_mode else 0, interval_hours, _now(),
                ))
            conn.commit()


def get_saved_searches(email: str = "") -> list[dict]:
    with _get_conn() as (conn, cur):
        if email:
            cur.execute("SELECT * FROM saved_searches WHERE email = ? ORDER BY created_at DESC", (email,))
        else:
            cur.execute("SELECT * FROM saved_searches ORDER BY created_at DESC")
        rows = cur.fetchall()
        results = []
        for row in rows:
            d = dict(row)
            try:
                d["sites"] = json.loads(d["sites"])
            except (json.JSONDecodeError, TypeError):
                d["sites"] = []
            try:
                d["keywords"] = json.loads(d["keywords"])
            except (json.JSONDecodeError, TypeError):
                d["keywords"] = []
            try:
                d["roles"] = json.loads(d["roles"])
            except (json.JSONDecodeError, TypeError):
                d["roles"] = []
            results.append(d)
        return results


def delete_saved_search(sid: str) -> bool:
    with _write_lock:
        with _get_conn() as (conn, cur):
            cur.execute("DELETE FROM saved_searches WHERE id = ?", (sid,))
            conn.commit()
            return cur.rowcount > 0


# ── Visits ──


def log_visit_start(visit_id: str, ip_address: str, user_agent: str = "",
                     device_type: str = "unknown", referer: str = "",
                     path: str = "/", session_id: str = "",
                     user_email: str = "", country: str = "",
                     city: str = "", region: str = "") -> dict:
    now = _now()
    with _write_lock:
        with _get_conn() as (conn, cur):
            cur.execute("""INSERT OR IGNORE INTO visits
                (visit_id, ip_address, user_agent, device_type, referer, path, session_id, user_email, duration_seconds, heartbeats, country, city, region, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?, ?)""",
                         (visit_id, ip_address, user_agent, device_type, referer,
                          path, session_id, user_email, country, city, region, now))
            conn.commit()
    return {"visit_id": visit_id, "created_at": now}


def update_visit_ping(visit_id: str, elapsed_seconds: float):
    now = _now()
    with _write_lock:
        with _get_conn() as (conn, cur):
            cur.execute("""UPDATE visits SET duration_seconds = ?, last_heartbeat = ?,
                           heartbeats = heartbeats + 1 WHERE visit_id = ?""",
                         (elapsed_seconds, now, visit_id))
            conn.commit()


def finalize_visit(visit_id: str, total_duration: float):
    now = _now()
    with _write_lock:
        with _get_conn() as (conn, cur):
            cur.execute("""UPDATE visits SET duration_seconds = MAX(duration_seconds, ?),
                           last_heartbeat = ? WHERE visit_id = ?""",
                         (total_duration, now, visit_id))
            conn.commit()


def get_visit_stats() -> dict:
    with _get_conn() as (conn, cur):
        cur.execute("SELECT COUNT(*) FROM visits")
        total_visits = cur.fetchone()[0]
        cur.execute("SELECT COUNT(DISTINCT ip_address) FROM visits")
        unique_visitors = cur.fetchone()[0]
        cur.execute("SELECT COALESCE(AVG(duration_seconds), 0) FROM visits WHERE duration_seconds > 0")
        avg_duration = round(cur.fetchone()[0], 1)
        cur.execute("""SELECT device_type, COUNT(*) as cnt FROM visits
                       WHERE device_type != '' GROUP BY device_type ORDER BY cnt DESC""")
        devices = {r["device_type"]: r["cnt"] for r in cur.fetchall()}
        cur.execute("""SELECT ip_address, COUNT(*) as visit_count,
                       MIN(created_at) as first_visit, MAX(created_at) as last_visit,
                       COALESCE(AVG(duration_seconds), 0) as avg_duration,
                       (SELECT country FROM visits v2 WHERE v2.ip_address = visits.ip_address AND v2.country != '' ORDER BY v2.created_at DESC LIMIT 1) as country
                       FROM visits GROUP BY ip_address
                       ORDER BY visit_count DESC LIMIT 100""")
        by_ip = []
        for r in cur.fetchall():
            by_ip.append({
                "ip": r["ip_address"], "count": r["visit_count"],
                "first_visit": r["first_visit"], "last_visit": r["last_visit"],
                "avg_duration": round(r["avg_duration"], 1),
                "country": r["country"] or "",
            })
        return {
            "total_visits": total_visits,
            "unique_visitors": unique_visitors,
            "avg_duration_seconds": avg_duration,
            "devices": devices,
            "by_ip": by_ip,
        }


def get_visits(limit: int = 200) -> list[dict]:
    with _get_conn() as (conn, cur):
        cur.execute("""SELECT * FROM visits ORDER BY created_at DESC LIMIT ?""", (limit,))
        return [dict(r) for r in cur.fetchall()]


# ── IP Geolocation ──

import requests as _requests

_ip_geo_cache: dict[str, dict] = {}
_IP_GEO_CACHE_TTL = 86400  # 24h


def _resolve_ip_sync(ip: str) -> dict:
    """Look up IP geolocation via ip-api.com. Returns {country, city, region}."""
    if ip in ("127.0.0.1", "::1", "localhost", "unknown"):
        return {"country": "Local", "city": "", "region": ""}
    cached = _ip_geo_cache.get(ip)
    if cached:
        return cached
    try:
        resp = _requests.get(f"http://ip-api.com/json/{ip}?fields=status,country,city,regionName",
                             timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "success":
                result = {
                    "country": data.get("country", ""),
                    "city": data.get("city", ""),
                    "region": data.get("regionName", ""),
                }
                _ip_geo_cache[ip] = result
                return result
    except Exception:
        pass
    return {"country": "", "city": "", "region": ""}


def _store_geo(ip: str, visit_id: str):
    """Synchronous: resolve IP and store result in DB."""
    try:
        loc = _resolve_ip_sync(ip)
        if loc.get("country") and visit_id:
            with _write_lock:
                with _get_conn() as (conn2, cur2):
                    cur2.execute(
                        "UPDATE visits SET country=?, city=?, region=? WHERE visit_id=?",
                        (loc["country"], loc["city"], loc["region"], visit_id))
                    conn2.commit()
    except Exception:
        pass


# ── Referral Requests ──

def get_pending_referral(from_email: str, to_email: str, job_url: str, company: str = "") -> Optional[dict]:
    with _get_conn() as (conn, cur):
        cur.execute(
            "SELECT * FROM referral_requests WHERE from_email = ? AND to_email = ? AND job_url = ? AND company = ? AND status = 'pending' ORDER BY id DESC LIMIT 1",
            (from_email, to_email, job_url, company))
        row = cur.fetchone()
        return dict(row) if row else None


def get_monthly_sent_count(email: str) -> int:
    with _get_conn() as (conn, cur):
        cur.execute("SELECT COUNT(*) FROM referral_requests WHERE from_email = ? AND created_at >= date('now', 'start of month') AND status NOT IN ('cancelled', 'declined')", (email,))
        return cur.fetchone()[0]


def create_referral_request(from_email: str, to_email: str, job_url: str, job_title: str,
                            company: str, match_score: int = 0, message: str = "") -> Optional[int]:
    now = _now()
    with _write_lock:
        with _get_conn() as (conn, cur):
            cur.execute(
                "INSERT INTO referral_requests (from_email, to_email, job_url, job_title, company, match_score, message, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
                (from_email, to_email, job_url, job_title, company, match_score, message, now, now))
            conn.commit()
            return cur.lastrowid


def get_incoming_referrals(email: str) -> list[dict]:
    with _get_conn() as (conn, cur):
        cur.execute(
            "SELECT * FROM referral_requests WHERE to_email = ? AND status != 'cancelled' ORDER BY created_at DESC", (email,))
        return [dict(r) for r in cur.fetchall()]


def get_outgoing_referrals(email: str) -> list[dict]:
    with _get_conn() as (conn, cur):
        cur.execute(
            "SELECT * FROM referral_requests WHERE from_email = ? ORDER BY created_at DESC", (email,))
        return [dict(r) for r in cur.fetchall()]


def update_referral_status(req_id: int, status: str) -> bool:
    now = _now()
    with _write_lock:
        with _get_conn() as (conn, cur):
            if status == "accepted":
                cur.execute("UPDATE referral_requests SET status = ?, accepted_at = ?, updated_at = ? WHERE id = ?",
                             (status, now, now, req_id))
            else:
                cur.execute("UPDATE referral_requests SET status = ?, updated_at = ? WHERE id = ?",
                             (status, now, req_id))
            conn.commit()
            return cur.rowcount > 0


def get_referral_request(req_id: int) -> Optional[dict]:
    with _get_conn() as (conn, cur):
        cur.execute("SELECT * FROM referral_requests WHERE id = ?", (req_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def confirm_referral(req_id: int, email: str, role: str) -> dict:
    """
    role: 'receiver' or 'sender'
    Returns {ok, credits_awarded, receiver_confirmed, sender_confirmed, error}
    """
    req = get_referral_request(req_id)
    if not req:
        return {"ok": False, "error": "Request not found"}
    if req["status"] != "accepted":
        return {"ok": False, "error": "Request is not accepted"}
    if req.get("credit_awarded"):
        return {"ok": False, "error": "Credits already awarded"}

    if role == "receiver" and req["to_email"] != email:
        return {"ok": False, "error": "Not authorized"}
    if role == "sender" and req["from_email"] != email:
        return {"ok": False, "error": "Not authorized"}

    if req.get("accepted_at"):
        from datetime import datetime
        now_ts = datetime.utcnow().timestamp()
        try:
            accepted_ts = datetime.fromisoformat(req["accepted_at"]).timestamp()
        except Exception:
            accepted_ts = 0
        elapsed = now_ts - accepted_ts
        cooldown = 10 if DEV_MODE else 48 * 3600
        if elapsed < cooldown:
            remaining = int(cooldown - elapsed)
            if DEV_MODE:
                return {"ok": False, "error": f"Please wait {remaining}s before confirming",
                        "accepted_at": req["accepted_at"]}
            remaining_h = remaining // 3600
            remaining_m = remaining % 3600 // 60
            return {"ok": False, "error": f"Please wait {remaining_h}h {remaining_m}m before confirming",
                    "accepted_at": req["accepted_at"]}

    now = _now()
    field = "receiver_confirmed" if role == "receiver" else "sender_confirmed"

    with _write_lock:
        with _get_conn() as (conn, cur):
            cur.execute(f"UPDATE referral_requests SET {field} = 1, updated_at = ? WHERE id = ?", (now, req_id))
            conn.commit()

    updated = get_referral_request(req_id)
    credits_awarded = False
    if updated.get("receiver_confirmed") and updated.get("sender_confirmed"):
        with _write_lock:
            with _get_conn() as (conn2, cur2):
                cur2.execute("UPDATE referral_requests SET credit_awarded = 1, updated_at = ? WHERE id = ?", (now, req_id))
                cur2.execute("UPDATE users SET referral_credits = referral_credits + 10, updated_at = ? WHERE email = ?",
                             (now, req["to_email"]))
                conn2.commit()
                credits_awarded = True

    return {
        "ok": True,
        "credits_awarded": credits_awarded,
        "receiver_confirmed": 1 if credits_awarded or role == "receiver" else updated.get("receiver_confirmed", 0),
        "sender_confirmed": 1 if credits_awarded or role == "sender" else updated.get("sender_confirmed", 0),
    }

def complete_referral(req_id: int, referrer_email: str) -> bool:
    """Legacy wrapper — kept for backward compat. Delegates to confirm_referral."""
    result = confirm_referral(req_id, referrer_email, "receiver")
    return result.get("ok", False)


def add_custom_company(name: str) -> bool:
    name = name.strip()
    if not name:
        return False
    now = _now()
    with _write_lock:
        with _get_conn() as (conn, cur):
            try:
                cur.execute("INSERT INTO custom_companies (name, created_at) VALUES (?, ?)", (name, now))
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False


def batch_add_custom_companies(names: list[str]) -> int:
    """Insert multiple companies in a single transaction. Returns count inserted."""
    names = sorted(set(n.strip() for n in names if n.strip()))
    if not names:
        return 0
    now = _now()
    count = 0
    with _write_lock:
        with _get_conn() as (conn, cur):
            for name in names:
                try:
                    cur.execute("INSERT INTO custom_companies (name, created_at) VALUES (?, ?)", (name, now))
                    count += 1
                except sqlite3.IntegrityError:
                    pass
            conn.commit()
    return count


def get_custom_companies() -> list[str]:
    with _get_conn() as (conn, cur):
        cur.execute("SELECT name FROM custom_companies ORDER BY name")
        return [r["name"] for r in cur.fetchall()]

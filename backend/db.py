import sqlite3
import os
import json
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "job_agent.db")
_write_lock = threading.Lock()
_job_count_cache: dict[str, int] = {}


def _get_conn():
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn, conn.cursor()


def init_db():
    conn, cur = _get_conn()
    try:
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
        """)
        conn.commit()
        try:
            cur.execute("ALTER TABLE sessions ADD COLUMN elapsed_seconds REAL DEFAULT 0")
        except:
            pass
        try:
            cur.execute("ALTER TABLE sessions ADD COLUMN keywords TEXT DEFAULT '[]'")
        except:
            pass
        try:
            cur.execute("ALTER TABLE sessions ADD COLUMN roles TEXT DEFAULT '[]'")
        except:
            pass
        try:
            cur.execute("ALTER TABLE sessions ADD COLUMN location TEXT DEFAULT ''")
        except:
            pass
    finally:
        conn.close()


def gc_sessions(max_age_minutes: int = 240):
    with _write_lock:
        conn, cur = _get_conn()
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
        conn, cur = _get_conn()
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
        conn, cur = _get_conn()
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
    conn, cur = _get_conn()
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
        conn, cur = _get_conn()
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
        conn, cur = _get_conn()
        row = _job_to_row(sid, job)
        cur.execute("""INSERT INTO jobs
            (session_id, title, company, location, url, description, tags, ai_score, keyword_score, total_score, reason, salary, experience_level, is_raw, created_at)
            VALUES (:session_id, :title, :company, :location, :url, :description, :tags, :ai_score, :keyword_score, :total_score, :reason, :salary, :experience_level, :is_raw, :created_at)""", row)
        conn.commit()
        _job_count_cache.pop(sid, None)


def count_filtered_jobs(sid: str) -> int:
    if sid in _job_count_cache:
        return _job_count_cache[sid]
    conn, cur = _get_conn()
    cur.execute("SELECT COUNT(*) FROM jobs WHERE session_id = ? AND is_raw = 0", (sid,))
    count = cur.fetchone()[0]
    _job_count_cache[sid] = count
    return count


def get_filtered_jobs(sid: str, min_score: int = 0, site: str = "", experience_level: str = "") -> list:
    conn, cur = _get_conn()
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
        conn, cur = _get_conn()
        cur.execute("""INSERT INTO events (session_id, event, data, elapsed_seconds, created_at)
            VALUES (?, ?, ?, ?, ?)""", (sid, event, json.dumps(data or {}), elapsed, _now()))
        conn.commit()

def get_events(sid: str, limit: int = 50) -> list[dict]:
    conn, cur = _get_conn()
    cur.execute(
        "SELECT event, created_at FROM events WHERE session_id = ? ORDER BY id DESC LIMIT ?",
        (sid, limit),
    )
    rows = cur.fetchall()
    return [{"event": row[0], "created_at": row[1]} for row in rows][::-1]


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
        conn, cur = _get_conn()
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
    conn, cur = _get_conn()
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
    conn, cur = _get_conn()
    cur.execute("SELECT * FROM users WHERE email = ?", (email,))
    row = cur.fetchone()
    return dict(row) if row else None


def create_user(email: str, name: str) -> dict:
    now = _now()
    with _write_lock:
        conn, cur = _get_conn()
        cur.execute("INSERT OR IGNORE INTO users (email, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
                     (email, name, now, now))
        conn.commit()
    return {"email": email, "name": name, "created_at": now}


def update_user_name(email: str, name: str):
    with _write_lock:
        conn, cur = _get_conn()
        cur.execute("UPDATE users SET name = ?, updated_at = ? WHERE email = ?",
                     (name, _now(), email))
        conn.commit()


# ── Verification Codes ──

def save_verification_code(email: str, code: str, expires_at: str):
    with _write_lock:
        conn, cur = _get_conn()
        cur.execute("INSERT INTO verification_codes (email, code, expires_at, used, created_at) VALUES (?, ?, ?, 0, ?)",
                     (email, code, expires_at, _now()))
        conn.commit()


def verify_code(email: str, code: str) -> bool:
    with _write_lock:
        conn, cur = _get_conn()
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
        conn, cur = _get_conn()
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
        if cur.rowcount == 0:
            cur.execute("SELECT id FROM saved_jobs WHERE user_email = ? AND url = ?", (user_email, job.get("url", "")))
            row = cur.fetchone()
            row_id = row["id"] if row else 0
        else:
            row_id = cur.lastrowid
    return {"id": row_id, "saved": True}


def is_job_saved(user_email: str, url: str) -> bool:
    conn, cur = _get_conn()
    cur.execute("SELECT 1 FROM saved_jobs WHERE user_email = ? AND url = ?", (user_email, url))
    return cur.fetchone() is not None


def batch_check_saved(user_email: str, urls: list[str]) -> dict[str, int]:
    if not user_email or not urls:
        return {}
    conn, cur = _get_conn()
    placeholders = ",".join("?" for _ in urls)
    cur.execute(
        f"SELECT id, url FROM saved_jobs WHERE user_email = ? AND url IN ({placeholders})",
        [user_email] + urls,
    )
    saved = {row["url"]: row["id"] for row in cur.fetchall()}
    return saved


def get_saved_jobs(user_email: str, status: str = "") -> list[dict]:
    conn, cur = _get_conn()
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
        conn, cur = _get_conn()
        cur.execute("UPDATE saved_jobs SET application_status = ?, updated_at = ? WHERE id = ?",
                     (status, _now(), job_id))
        conn.commit()
        return cur.rowcount > 0


def delete_saved_job(job_id: int) -> bool:
    with _write_lock:
        conn, cur = _get_conn()
        cur.execute("DELETE FROM saved_jobs WHERE id = ?", (job_id,))
        conn.commit()
        return cur.rowcount > 0


def get_saved_jobs_status_counts(user_email: str) -> dict[str, int]:
    conn, cur = _get_conn()
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
        conn, cur = _get_conn()
        cur.execute("""INSERT OR REPLACE INTO saved_searches
            (id, email, name, sites, keywords, roles, location, internship_mode, interval_hours, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
                sid, email, name,
                json.dumps(sites), json.dumps(keywords), json.dumps(roles),
                location, 1 if internship_mode else 0, interval_hours, _now(),
            ))
        conn.commit()


def get_saved_searches(email: str = "") -> list[dict]:
    conn, cur = _get_conn()
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
        conn, cur = _get_conn()
        cur.execute("DELETE FROM saved_searches WHERE id = ?", (sid,))
        conn.commit()
        return cur.rowcount > 0

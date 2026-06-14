import sqlite3
import os
import json
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "job_agent.db")
_write_lock = threading.Lock()


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
                keywords_count INTEGER DEFAULT 0,
                roles_count INTEGER DEFAULT 0,
            resume_length INTEGER DEFAULT 0,
            scraped INTEGER DEFAULT 0,
            elapsed_seconds REAL DEFAULT 0
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
            CREATE INDEX IF NOT EXISTS idx_jobs_session ON jobs(session_id);
            CREATE INDEX IF NOT EXISTS idx_jobs_raw ON jobs(session_id, is_raw);
            CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);
        """)
        conn.commit()
        try:
            cur.execute("ALTER TABLE sessions ADD COLUMN elapsed_seconds REAL DEFAULT 0")
        except:
            pass
    finally:
        conn.close()


def gc_sessions(max_age_minutes: int = 240):
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
    conn, cur = _get_conn()
    now = _now()
    fields = {
        "id": sid, "created_at": now, "updated_at": now,
        "sites": json.dumps(kwargs.get("sites", [])),
        "keywords_count": kwargs.get("keywords_count", 0),
        "roles_count": kwargs.get("roles_count", 0),
        "resume_length": kwargs.get("resume_length", 0),
        "internship_mode": 1 if kwargs.get("internship_mode") else 0,
    }
    cur.execute("""INSERT OR REPLACE INTO sessions
        (id, created_at, updated_at, sites, keywords_count, roles_count, resume_length, internship_mode)
        VALUES (:id, :created_at, :updated_at, :sites, :keywords_count, :roles_count, :resume_length, :internship_mode)""", fields)
    conn.commit()


def update_session(sid: str, **kwargs):
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
    try:
        d["sites"] = json.loads(d["sites"])
    except (json.JSONDecodeError, TypeError):
        d["sites"] = []
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
    conn, cur = _get_conn()
    cur.execute("DELETE FROM jobs WHERE session_id = ? AND is_raw = 0", (sid,))
    rows = [_job_to_row(sid, j) for j in jobs]
    if rows:
        cur.executemany("""INSERT INTO jobs
            (session_id, title, company, location, url, description, tags, ai_score, keyword_score, total_score, reason, salary, experience_level, is_raw, created_at)
            VALUES (:session_id, :title, :company, :location, :url, :description, :tags, :ai_score, :keyword_score, :total_score, :reason, :salary, :experience_level, :is_raw, :created_at)""", rows)
    conn.commit()


def add_filtered_job(sid: str, job: dict):
    conn, cur = _get_conn()
    row = _job_to_row(sid, job)
    cur.execute("""INSERT INTO jobs
        (session_id, title, company, location, url, description, tags, ai_score, keyword_score, total_score, reason, salary, experience_level, is_raw, created_at)
        VALUES (:session_id, :title, :company, :location, :url, :description, :tags, :ai_score, :keyword_score, :total_score, :reason, :salary, :experience_level, :is_raw, :created_at)""", row)
    conn.commit()


def count_filtered_jobs(sid: str) -> int:
    conn, cur = _get_conn()
    cur.execute("SELECT COUNT(*) FROM jobs WHERE session_id = ? AND is_raw = 0", (sid,))
    return cur.fetchone()[0]


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
    conn, cur = _get_conn()
    cur.execute("""INSERT INTO events (session_id, event, data, elapsed_seconds, created_at)
        VALUES (?, ?, ?, ?, ?)""", (sid, event, json.dumps(data or {}), elapsed, _now()))
    conn.commit()


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
    add_event(session_id or "", "lead_captured", {"email": email, "has_name": bool(name), "lead_id": lead_id})
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

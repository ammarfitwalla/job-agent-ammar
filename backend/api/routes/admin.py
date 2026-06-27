import json
import os
from datetime import datetime, timedelta
from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _classify(s):
    if s["status"] == "error":
        return "Error"
    if s["cancel"]:
        return "Cancelled"
    if s["status"] == "running":
        return "Abandoned"
    return "Completed"


def _get_session_events(sids: list[str]) -> dict[str, list[str]]:
    from db import _get_conn
    if not sids:
        return {}
    conn, cur = _get_conn()
    placeholders = ",".join("?" for _ in sids)
    cur.execute(
        f"SELECT session_id, event FROM events WHERE session_id IN ({placeholders})",
        sids,
    )
    result = {sid: [] for sid in sids}
    for row in cur.fetchall():
        if row["session_id"] in result:
            result[row["session_id"]].append(row["event"])
    return result


@router.get("/stats")
async def admin_stats():
    from db import _get_conn

    conn, cur = _get_conn()

    cur.execute("SELECT COUNT(*) FROM sessions")
    total_sessions = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM sessions WHERE cancel = 1")
    cancelled = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM sessions WHERE status = 'error'")
    errors = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM sessions WHERE status = 'running'")
    abandoned = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM sessions WHERE status = 'done' AND cancel = 0")
    completed = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM leads")
    total_leads = cur.fetchone()[0]

    cur.execute("SELECT SUM(scraped) FROM sessions")
    total_raw = cur.fetchone()[0] or 0

    cur.execute("SELECT COUNT(*) FROM jobs WHERE is_raw = 0")
    total_relevant = cur.fetchone()[0]

    cur.execute(
        "SELECT AVG(elapsed_seconds) FROM sessions WHERE status = 'done' AND cancel = 0 AND elapsed_seconds > 0"
    )
    avg_duration = round(cur.fetchone()[0] or 0, 1)

    cur.execute("""
        SELECT DATE(created_at) as day, COUNT(*) as cnt
        FROM sessions
        WHERE created_at >= DATE('now', '-14 days')
        GROUP BY day ORDER BY day
    """)
    daily = [{"day": r["day"], "count": r["cnt"]} for r in cur.fetchall()]

    cur.execute("""
        SELECT internship_mode,
               COUNT(*) as total,
               SUM(CASE WHEN cancel = 1 THEN 1 ELSE 0 END) as cancelled,
               SUM(CASE WHEN status = 'done' AND cancel = 0 THEN 1 ELSE 0 END) as completed
        FROM sessions GROUP BY internship_mode
    """)
    by_mode = {}
    for r in cur.fetchall():
        by_mode["internship" if r["internship_mode"] else "normal"] = {
            "total": r["total"], "cancelled": r["cancelled"], "completed": r["completed"],
        }

    return {
        "total_sessions": total_sessions,
        "completed": completed,
        "cancelled": cancelled,
        "abandoned": abandoned,
        "errors": errors,
        "total_leads": total_leads,
        "total_raw_jobs": total_raw,
        "total_relevant_jobs": total_relevant,
        "avg_duration_seconds": avg_duration,
        "daily": daily,
        "by_mode": by_mode,
    }


@router.get("/sessions")
async def admin_sessions():
    from db import _get_conn

    conn, cur = _get_conn()
    cur.execute("SELECT * FROM sessions ORDER BY created_at DESC")
    rows = cur.fetchall()
    sessions = []
    for r in rows:
        s = dict(r)
        s["internship_mode"] = bool(s["internship_mode"])
        s["cancel"] = bool(s["cancel"])
        for field in ("sites", "keywords", "roles"):
            try:
                s[field] = json.loads(s[field])
            except (json.JSONDecodeError, TypeError):
                s[field] = []
        sessions.append(s)

    sids = [s["id"] for s in sessions]
    events_map = _get_session_events(sids)

    for s in sessions:
        evs = events_map.get(s["id"], [])
        s["classification"] = _classify(s)
        s["has_stop_event"] = any("stop" in e.lower() or "cancel" in e.lower() for e in evs)

    cur.execute(
        "SELECT session_id, COUNT(*) as cnt FROM jobs WHERE is_raw = 0 GROUP BY session_id"
    )
    job_counts = {r["session_id"]: r["cnt"] for r in cur.fetchall()}

    cur.execute(
        "SELECT session_id, title, url FROM jobs WHERE is_raw = 0 AND url != '' "
        "AND url IS NOT NULL ORDER BY COALESCE(total_score, 0) DESC"
    )
    job_links = {}
    for r in cur.fetchall():
        sid = r["session_id"]
        if sid not in job_links:
            job_links[sid] = []
        if len(job_links[sid]) < 3:
            job_links[sid].append({"title": r["title"], "url": r["url"]})

    for s in sessions:
        s["relevant_jobs"] = job_counts.get(s["id"], 0)
        s["job_links"] = job_links.get(s["id"], [])

    return {"sessions": sessions}


@router.get("/sessions/{sid}")
async def admin_session_detail(sid: str):
    from db import _get_conn, get_session

    s = get_session(sid)
    if not s:
        return {"error": "Session not found"}

    conn, cur = _get_conn()
    cur.execute(
        "SELECT event, elapsed_seconds, created_at FROM events WHERE session_id = ? ORDER BY id",
        (sid,),
    )
    events = [dict(r) for r in cur.fetchall()]

    cur.execute(
        "SELECT title, company, location, url, ai_score, keyword_score, total_score, reason, experience_level, salary, created_at "
        "FROM jobs WHERE session_id = ? AND is_raw = 0 ORDER BY COALESCE(total_score, 0) DESC",
        (sid,),
    )
    jobs = [dict(r) for r in cur.fetchall()]
    for j in jobs:
        j["url"] = j["url"] or ""

    s["classification"] = _classify(s)

    _resumes_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
        "resumes",
    )
    resume_path = os.path.join(_resumes_dir, f"{sid}.txt")
    has_resume = os.path.isfile(resume_path)

    return {
        "session": s,
        "events": events,
        "jobs": jobs,
        "resume_available": has_resume,
    }


@router.get("/sessions/{sid}/resume")
async def admin_resume(sid: str):
    _resumes_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
        "resumes",
    )
    path = os.path.join(_resumes_dir, f"{sid}.txt")
    if os.path.isfile(path):
        return FileResponse(path, filename=f"resume_{sid}.txt", media_type="text/plain")
    return {"error": "Resume not found"}


@router.get("/scores")
async def admin_scores():
    from db import _get_conn

    conn, cur = _get_conn()
    cur.execute(
        "SELECT total_score, ai_score, keyword_score, session_id, created_at "
        "FROM jobs WHERE is_raw = 0 AND total_score IS NOT NULL ORDER BY created_at DESC"
    )
    scores = [dict(r) for r in cur.fetchall()]

    bins = {}
    for j in scores:
        b = (j["total_score"] // 10) * 10
        bins[b] = bins.get(b, 0) + 1
    distribution = [{"range": f"{k}-{k+9}", "count": v} for k, v in sorted(bins.items())]

    return {"scores": scores, "distribution": distribution}


@router.get("/leads")
async def admin_leads():
    from db import get_leads

    return {"leads": get_leads(limit=500)}

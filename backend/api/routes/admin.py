import json
import os
import tempfile
from datetime import datetime, timedelta
from fastapi import APIRouter, UploadFile, File, Form
from fastapi.responses import FileResponse

router = APIRouter(prefix="/api/admin", tags=["admin"])

ADMIN_EMAIL = "ammarfitwalla@gmail.com"


def _classify(s):
    if s["status"] == "error":
        return "Error"
    if s["cancel"]:
        return "Cancelled"
    if s["status"] == "running":
        return "Abandoned"
    return "Completed"


def _resumes_dir() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "resumes")


def _resolve_session_resume(sid: str, s: dict):
    """Resolve the resume file for a session -> (filename, path) or ("", None).

    Priority: session's own resume_filename, then the user's profile resume,
    then legacy {sid}.* files, then the temp txt cache.
    """
    from db import get_user
    from db import _get_conn

    def _file(fname: str):
        p = os.path.join(_resumes_dir(), fname)
        if os.path.isfile(p):
            return fname, p
        return "", None

    fname = (s or {}).get("resume_filename") or ""
    if fname:
        fn, p = _file(fname)
        if p:
            return fn, p
    uemail = (s or {}).get("user_email") or ""
    if uemail:
        with _get_conn() as (conn, cur):
            cur.execute("SELECT resume_filename FROM users WHERE email = ?", (uemail,))
            row = cur.fetchone()
        if row and row["resume_filename"]:
            fn, p = _file(row["resume_filename"])
            if p:
                return fn, p
        local_part = uemail.split("@")[0].lower()
        if local_part:
            try:
                candidates = [
                    f for f in os.listdir(_resumes_dir())
                    if f.lower().startswith(f"resume_{local_part}_")
                ]
            except OSError:
                candidates = []
            if candidates:
                candidates.sort(
                    key=lambda f: os.path.getmtime(os.path.join(_resumes_dir(), f)),
                    reverse=True,
                )
                fn, p = _file(candidates[0])
                if p:
                    return fn, p
    for ext in (".pdf", ".docx", ".txt"):
        fn, p = _file(f"{sid}{ext}")
        if p:
            return fn, p
    tp = os.path.join(tempfile.gettempdir(), "job_agent_resumes", f"{sid}.txt")
    if os.path.isfile(tp):
        return f"{sid}.txt", tp
    return "", None


def _get_session_events(sids: list[str]) -> dict[str, list[str]]:
    from db import _get_conn
    if not sids:
        return {}
    with _get_conn() as (conn, cur):
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
    from db import _get_conn, get_visit_stats

    with _get_conn() as (conn, cur):

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

        cur.execute("SELECT COUNT(*) FROM users")
        total_users = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM leads")
        total_leads = cur.fetchone()[0]

        cur.execute("SELECT SUM(scraped) FROM sessions")
        total_scraped = cur.fetchone()[0] or 0

        cur.execute(
            """SELECT AVG(CASE WHEN elapsed_seconds > 0 THEN elapsed_seconds
                ELSE (julianday(updated_at) - julianday(created_at)) * 86400 END)
            FROM sessions WHERE status = 'done' AND cancel = 0"""
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

    visit_stats = get_visit_stats()

    return {
        "total_sessions": total_sessions,
        "completed": completed,
        "cancelled": cancelled,
        "abandoned": abandoned,
        "errors": errors,
        "total_users": total_users,
        "total_leads": total_leads,
        "total_scraped_jobs": total_scraped,
        "avg_duration_seconds": avg_duration,
        "daily": daily,
        "by_mode": by_mode,
        "total_visits": visit_stats["total_visits"],
        "unique_visitors": visit_stats["unique_visitors"],
        "visit_avg_duration_seconds": visit_stats["avg_duration_seconds"],
        "devices": visit_stats["devices"],
    }


@router.get("/sessions")
async def admin_sessions():
    from db import _get_conn

    with _get_conn() as (conn, cur):
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

    with _get_conn() as (conn, cur):
        for s in sessions:
            evs = events_map.get(s["id"], [])
            s["classification"] = _classify(s)
            s["has_stop_event"] = any("stop" in e.lower() or "cancel" in e.lower() for e in evs)

        cur.execute(
            "SELECT session_id, COUNT(*) as cnt FROM jobs WHERE is_raw = 1 GROUP BY session_id"
        )
        job_counts = {r["session_id"]: r["cnt"] for r in cur.fetchall()}

        cur.execute(
            "SELECT session_id, title, url FROM jobs WHERE is_raw = 1 AND url != '' "
            "AND url IS NOT NULL ORDER BY COALESCE(keyword_score, 0) DESC"
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
            fn, _ = _resolve_session_resume(s["id"], s)
            s["resume_available"] = bool(fn)

    return {"sessions": sessions}


@router.get("/sessions/{sid}")
async def admin_session_detail(sid: str):
    from db import _get_conn, get_session

    s = get_session(sid)
    if not s:
        return {"error": "Session not found"}

    email = s.get("user_email") or ""

    with _get_conn() as (conn, cur):
        if email:
            cur.execute(
                "SELECT id, title, company, url, location, salary, total_score, "
                "application_status, saved_at FROM saved_jobs "
                "WHERE user_email = ? ORDER BY saved_at DESC",
                (email,),
            )
            saved_jobs = [dict(r) for r in cur.fetchall()]
            for j in saved_jobs:
                j["url"] = j["url"] or ""
            from db import get_latest_referral_scores
            _scores = get_latest_referral_scores(email)
            for j in saved_jobs:
                m = _scores.get(j["url"])
                if m and not j.get("total_score"):
                    j["total_score"] = m

            cur.execute(
                "SELECT r.id, r.job_url, r.job_title, r.company, r.match_score, "
                "r.to_email, r.status, r.created_at, u.name AS to_name, u.company AS to_company "
                "FROM referral_requests r LEFT JOIN users u ON u.email = r.to_email "
                "WHERE r.from_email = ? ORDER BY r.created_at DESC",
                (email,),
            )
            referral_requests = [dict(r) for r in cur.fetchall()]
        else:
            saved_jobs = []
            referral_requests = []

    s["classification"] = _classify(s)

    fn, _ = _resolve_session_resume(sid, s)

    return {
        "session": s,
        "saved_jobs": saved_jobs,
        "referral_requests": referral_requests,
        "resume_available": bool(fn),
    }


@router.get("/sessions/{sid}/resume")
async def admin_resume(sid: str):
    from db import get_session

    s = get_session(sid)
    fn, path = _resolve_session_resume(sid, s or {})
    if not path:
        return {"error": "Resume not found"}
    ext = os.path.splitext(fn)[1].lstrip(".").lower()
    mime = {"pdf": "application/pdf", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "txt": "text/plain"}.get(ext, "application/octet-stream")
    return FileResponse(path, filename=f"resume_{sid}_{fn}", media_type=mime)


@router.get("/scores")
async def admin_scores():
    from db import _get_conn

    with _get_conn() as (conn, cur):
        cur.execute(
            "SELECT keyword_score, session_id, created_at "
            "FROM jobs WHERE is_raw = 1 AND keyword_score IS NOT NULL ORDER BY created_at DESC"
        )
        scores = [dict(r) for r in cur.fetchall()]

    bins = {}
    for j in scores:
        b = (j["keyword_score"] // 10) * 10
        bins[b] = bins.get(b, 0) + 1
    distribution = [{"range": f"{k}-{k+9}", "count": v} for k, v in sorted(bins.items())]

    return {"scores": scores, "distribution": distribution}


@router.get("/registrations")
async def admin_registrations():
    from db import get_all_users

    return {"registrations": get_all_users(limit=500)}


@router.get("/visits")
async def admin_visits():
    from db import get_visits, get_visit_stats

    return {"visits": get_visits(limit=200), "stats": get_visit_stats()}


@router.get("/leads")
async def admin_leads():
    from db import get_leads

    return {"leads": get_leads(limit=500)}


@router.get("/db/info")
async def admin_db_info(email: str = ""):
    if email != ADMIN_EMAIL:
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})
    from db import _get_conn, _DB_PATH

    with _get_conn() as (conn, cur):
        cur.execute("SELECT COUNT(*) FROM sessions")
        sessions = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM users")
        users = cur.fetchone()[0]

    size_bytes = os.path.getsize(_DB_PATH) if os.path.isfile(_DB_PATH) else 0
    return {"size_bytes": size_bytes, "size_mb": round(size_bytes / 1048576, 2), "sessions": sessions, "users": users}


@router.post("/db/restore")
async def admin_db_restore(file: UploadFile = File(...), email: str = Form("")):
    if email != ADMIN_EMAIL:
        return {"ok": False, "error": "Unauthorized"}
    from db import _DB_PATH, init_db

    # Remove stale WAL/SHM files so SQLite doesn't merge old pages
    for ext in ("-wal", "-shm"):
        p = _DB_PATH + ext
        if os.path.isfile(p):
            os.remove(p)

    contents = await file.read()
    if contents[:16] != b"SQLite format 3\x00":
        return {"ok": False, "error": "Not a valid SQLite database file"}

    with open(_DB_PATH, "wb") as f:
        f.write(contents)

    init_db()

    # Force a clean WAL checkpoint
    from db import _get_conn
    with _get_conn() as (conn, cur):
        cur.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    return {"ok": True, "message": "Database restored successfully", "size_bytes": len(contents)}


@router.post("/db/merge")
async def admin_db_merge(file: UploadFile = File(...), email: str = Form("")):
    if email != ADMIN_EMAIL:
        return {"ok": False, "error": "Unauthorized"}
    from db import _get_conn
    import tempfile, os, uuid

    contents = await file.read()
    if contents[:16] != b"SQLite format 3\x00":
        return {"ok": False, "error": "Not a valid SQLite database file"}

    tmp = os.path.join(tempfile.gettempdir(), f"merge_{uuid.uuid4().hex}.db")
    with open(tmp, "wb") as f:
        f.write(contents)

    try:
        with _get_conn() as (conn, cur):
            cur.execute(f"ATTACH DATABASE ? AS upload", (tmp,))

            table_cols = {
                "sessions": ["id","created_at","updated_at","status","internship_mode","pass_num","max_passes","filtered_gen","cancel","queue_position","sites","keywords","roles","keywords_count","roles_count","resume_length","scraped","location"],
                "users": ["email","name","company","position","linkedin_url","resume_filename","referral_credits","created_at","updated_at"],
                "saved_searches": ["id","email","name","sites","keywords","roles","location","internship_mode","interval_hours","last_run_at","created_at"],
                "jobs": ["session_id","title","company","location","url","description","tags","ai_score","keyword_score","total_score","reason","salary","experience_level","is_raw","created_at"],
                "events": ["session_id","event","data","elapsed_seconds","created_at"],
                "leads": ["session_id","email","name","roles","location","keywords","internship_mode","resume_snippet","source","created_at"],
                "visits": ["visit_id","ip_address","user_agent","device_type","referer","path","session_id","user_email","duration_seconds","heartbeats","country","city","region","created_at","last_heartbeat"],
                "saved_jobs": ["user_email","title","company","url","location","salary","total_score","ai_score","keyword_score","reason","experience_level","tags","site","application_status","saved_at","updated_at"],
                "referral_requests": ["from_email","to_email","job_url","job_title","company","match_score","message","status","credit_awarded","accepted_at","receiver_confirmed","sender_confirmed","created_at","updated_at"],
                "custom_companies": ["name","created_at"],
                "verification_codes": ["email","code","expires_at","used","created_at"],
            }
            counts = {}

            for table, cols in table_cols.items():
                if cols is None:
                    cur.execute(f"INSERT OR IGNORE INTO main.{table} SELECT * FROM upload.{table}")
                else:
                    col_list = ",".join(f'"{c}"' for c in cols)
                    cur.execute(f"INSERT OR IGNORE INTO main.{table}({col_list}) SELECT {col_list} FROM upload.{table}")
                counts[table] = cur.rowcount

            conn.commit()

            try:
                cur.execute("DETACH DATABASE upload")
            except Exception:
                pass

        return {"ok": True, "inserted": {t: c for t, c in counts.items() if c > 0}}

    finally:
        if os.path.isfile(tmp):
            os.unlink(tmp)


@router.post("/resume/upload")
async def admin_resume_upload(files: list[UploadFile] = File(...), email: str = Form("")):
    if email != ADMIN_EMAIL:
        return {"ok": False, "error": "Unauthorized"}
    resumes_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "resumes")
    os.makedirs(resumes_dir, exist_ok=True)
    results = []
    for f in files:
        try:
            contents = await f.read()
            path = os.path.join(resumes_dir, f.filename or f"unnamed_{id(f)}")
            with open(path, "wb") as wf:
                wf.write(contents)
            results.append({"filename": f.filename, "ok": True, "size_bytes": len(contents)})
        except Exception as e:
            results.append({"filename": f.filename, "ok": False, "error": str(e)})
    return {"ok": True, "files": results}

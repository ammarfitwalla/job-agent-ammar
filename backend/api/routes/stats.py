from fastapi import APIRouter

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/public")
async def public_stats():
    from db import _get_conn

    conn, cur = _get_conn()

    cur.execute("SELECT COUNT(*) FROM users")
    total_users = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM sessions WHERE status != 'idle'")
    total_searches = cur.fetchone()[0]

    cur.execute("""
        SELECT COALESCE(SUM(CASE WHEN s.scraped > j.cnt THEN s.scraped ELSE j.cnt END), 0)
        FROM sessions s
        LEFT JOIN (SELECT session_id, COUNT(*) as cnt FROM jobs WHERE is_raw = 0 GROUP BY session_id) j ON j.session_id = s.id
    """)
    total_raw_jobs = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM jobs WHERE is_raw = 0")
    total_relevant_jobs = cur.fetchone()[0]

    return {
        "total_users": total_users,
        "total_searches": total_searches,
        "total_raw_jobs": total_raw_jobs,
        "total_relevant_jobs": total_relevant_jobs,
    }

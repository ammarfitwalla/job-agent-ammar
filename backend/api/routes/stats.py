from fastapi import APIRouter

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/public")
async def public_stats():
    from db import _get_conn

    with _get_conn() as (conn, cur):

        cur.execute("SELECT COUNT(*) FROM users")
        total_users = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM sessions WHERE status != 'idle'")
        total_searches = cur.fetchone()[0]

        cur.execute("SELECT COALESCE(SUM(scraped), 0) FROM sessions")
        total_raw_jobs = cur.fetchone()[0]

        cur.execute("SELECT COALESCE(SUM(job_count), 0) FROM job_cache")
        total_cached_jobs = cur.fetchone()[0]

        return {
            "total_users": total_users,
            "total_searches": total_searches,
            "total_raw_jobs": total_raw_jobs,
            "total_cached_jobs": total_cached_jobs,
        }

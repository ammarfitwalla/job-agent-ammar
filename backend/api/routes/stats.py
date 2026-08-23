from fastapi import APIRouter

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/public")
async def public_stats():
    from db import _get_conn

    with _get_conn() as (conn, cur):
        cur.execute("SELECT COUNT(*) FROM sessions")
        total_searches = cur.fetchone()[0]

        cur.execute("SELECT COALESCE(SUM(job_count), 0) FROM job_cache")
        total_scraped = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM users")
        total_users = cur.fetchone()[0]

        cur.execute("SELECT COUNT(DISTINCT LOWER(company)) FROM users WHERE company != ''")
        total_companies = cur.fetchone()[0]

        return {
            "total_searches": total_searches,
            "total_scraped": total_scraped,
            "total_users": total_users,
            "total_companies": total_companies,
        }

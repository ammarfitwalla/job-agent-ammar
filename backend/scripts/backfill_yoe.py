"""One-off backfill of the jobs.yoe_bucket column.

Classifies every job that still has an empty yoe_bucket using the same
classifier the scraper now applies, so previously saved searches get the
bucket dropdown too.

Run (from anywhere):

    D:\\Python\\Python310\\python.exe backend\\scripts\\backfill_yoe.py

Exits 0 and reports how many jobs were updated. Uses the real job_agent.db.
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import db  # noqa: E402
from utils.experience_level import yoe_bucket_from_job  # noqa: E402


def backfill():
    with db._get_conn() as (conn, cur):
        cur.execute("SELECT id, title, description, job_level FROM jobs WHERE yoe_bucket IS NULL OR yoe_bucket = ''")
        rows = cur.fetchall()
    updates = [
        (yoe_bucket_from_job(r["title"], r["description"], r["job_level"]), r["id"])
        for r in rows
    ]
    if updates:
        with db._write_lock:
            with db._get_conn() as (conn, cur):
                cur.executemany("UPDATE jobs SET yoe_bucket = ? WHERE id = ?", updates)
                conn.commit()
    print(f"[BACKFILL-YOE] {len(updates)} jobs updated.")


if __name__ == "__main__":
    backfill()
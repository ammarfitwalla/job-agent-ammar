import sqlite3, json
conn = sqlite3.connect("backend/job_agent.db")
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute("SELECT id FROM sessions ORDER BY created_at DESC LIMIT 1")
sid = cur.fetchone()[0]
print(f"Session: {sid}")
cur.execute("SELECT title, company, url, total_score FROM jobs WHERE session_id = ? AND is_raw = 0 LIMIT 3", (sid,))
jobs = [dict(r) for r in cur.fetchall()]
print(f"Job count: {len(jobs)}")
for j in jobs:
    print(f"  title={j['title']}, url={repr(j['url'])}, url_bool={bool(j['url'])}")
conn.close()

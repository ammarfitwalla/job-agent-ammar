import sqlite3, json

conn = sqlite3.connect("D:\\AF\\Projects\\job-agent-ammar\\backend\\job_agent.db")

# Find all DevOps Engineer jobs in Bamboo Flat
rows = conn.execute(
    "SELECT role, city, state, job_count, jobs_json FROM job_cache WHERE city='Bamboo Flat' AND site='naukri'"
).fetchall()

for role, city, state, count, jobs_json in rows:
    jobs = json.loads(jobs_json)
    print(f"\n{'='*70}")
    print(f"Role: {role} | City: {city} | State: {state} | Jobs: {count}")
    print(f"{'='*70}")
    for i, j in enumerate(jobs, 1):
        print(f"  #{i} | {j.get('title', '?')}")
        print(f"       Location: '{j.get('location', '')}'")
        print(f"       URL: {j.get('url', '')[:80]}")

# Also check how many distinct locations exist in ALL naukri cache entries
print(f"\n{'='*70}")
print("ALL DISTINCT NAUKRI JOB LOCATIONS (top 30)")
print(f"{'='*70}")
rows2 = conn.execute("SELECT jobs_json FROM job_cache WHERE site='naukri'").fetchall()
loc_counts = {}
for (jobs_json,) in rows2:
    for j in json.loads(jobs_json):
        loc = j.get("location", "") or "(empty)"
        loc_counts[loc] = loc_counts.get(loc, 0) + 1
for loc, cnt in sorted(loc_counts.items(), key=lambda x: -x[1])[:30]:
    print(f"  {cnt:4d} | {loc}")

conn.close()

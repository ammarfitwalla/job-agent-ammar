"""Test that the job_cache UNIQUE constraint migration works correctly."""
import os
import sys
import sqlite3
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)


def test_migration():
    # 1. Create a DB with the OLD schema (7-column UNIQUE, no is_remote)
    old_db = os.path.join(tempfile.gettempdir(), "test_old_schema.db")
    if os.path.exists(old_db):
        os.remove(old_db)
    conn = sqlite3.connect(old_db)
    conn.execute("""
        CREATE TABLE job_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            site TEXT NOT NULL,
            city TEXT NOT NULL DEFAULT '',
            state TEXT NOT NULL DEFAULT '',
            country TEXT NOT NULL DEFAULT '',
            internship_mode INTEGER NOT NULL DEFAULT 0,
            hours_old INTEGER NOT NULL DEFAULT 168,
            is_remote INTEGER NOT NULL DEFAULT 0,
            job_count INTEGER NOT NULL DEFAULT 0,
            jobs_json TEXT NOT NULL DEFAULT '[]',
            scraped_at TEXT NOT NULL,
            UNIQUE(role, site, city, state, country, internship_mode, hours_old)
        )
    """)
    conn.execute(
        "INSERT INTO job_cache (role, site, city, state, country, internship_mode, "
        "hours_old, job_count, jobs_json, scraped_at) "
        "VALUES ('Data Analyst', 'naukri', 'Bengaluru', 'Karnataka', 'in', 0, 168, "
        "5, '[]', '2026-08-23T00:00:00')"
    )
    conn.commit()
    print("OLD schema DB created with 1 row")

    # Verify old UNIQUE doesn't have is_remote
    cur = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='job_cache'"
    )
    old_sql = cur.fetchone()[0]
    un_idx = old_sql.upper().find("UNIQUE(")
    un_part = old_sql[un_idx:] if un_idx >= 0 else ""
    assert "is_remote" not in un_part.lower(), "Expected old UNIQUE without is_remote"
    conn.close()

    # 2. Now run our migration logic (same as init_db)
    conn = sqlite3.connect(old_db)
    cur = conn.cursor()
    cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='job_cache'")
    row = cur.fetchone()
    _sql = row[0] or ""
    _un_idx = _sql.upper().find("UNIQUE(")
    _un_part = _sql[_un_idx:] if _un_idx >= 0 else ""
    _needs_rebuild = "is_remote" not in _un_part.lower()
    assert _needs_rebuild, "Should detect old schema needs rebuild"
    print("Detected old schema - rebuilding...")

    cur.execute("ALTER TABLE job_cache RENAME TO job_cache_old")
    cur.execute("""
        CREATE TABLE job_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            site TEXT NOT NULL,
            city TEXT NOT NULL DEFAULT '',
            state TEXT NOT NULL DEFAULT '',
            country TEXT NOT NULL DEFAULT '',
            internship_mode INTEGER NOT NULL DEFAULT 0,
            hours_old INTEGER NOT NULL DEFAULT 168,
            is_remote INTEGER NOT NULL DEFAULT 0,
            job_count INTEGER NOT NULL DEFAULT 0,
            jobs_json TEXT NOT NULL DEFAULT '[]',
            scraped_at TEXT NOT NULL,
            UNIQUE(role, site, city, state, country, internship_mode, hours_old, is_remote)
        )
    """)
    cur.execute(
        "CREATE INDEX idx_job_cache_key ON job_cache(role, site, city, state, "
        "country, internship_mode, hours_old, is_remote)"
    )
    cur.execute("INSERT OR IGNORE INTO job_cache SELECT * FROM job_cache_old")
    cur.execute("DROP TABLE job_cache_old")
    conn.commit()
    print("Migration done")

    # 3. Verify new schema works with ON CONFLICT
    cur.execute(
        "INSERT INTO job_cache (role, site, city, state, country, internship_mode, "
        "hours_old, is_remote, job_count, jobs_json, scraped_at) "
        "VALUES ('Data Analyst', 'naukri', 'Bengaluru', 'Karnataka', 'in', 0, 168, "
        "0, 10, '[]', '2026-08-23T01:00:00') "
        "ON CONFLICT(role, site, city, state, country, internship_mode, hours_old, "
        "is_remote) DO UPDATE SET job_count = excluded.job_count, "
        "jobs_json = excluded.jobs_json, scraped_at = excluded.scraped_at"
    )
    conn.commit()
    print("INSERT ON CONFLICT succeeded")

    # 4. Verify old data survived migration
    cur.execute("SELECT role, city, state, is_remote, job_count FROM job_cache")
    rows = cur.fetchall()
    assert len(rows) == 1, f"Expected 1 row after migration, got {len(rows)}"
    assert rows[0] == ("Data Analyst", "Bengaluru", "Karnataka", 0, 10)
    print(f"Data survived: {rows[0]}")

    # 5. Verify duplicate detection works (same 8-field key should upsert)
    cur.execute(
        "INSERT INTO job_cache (role, site, city, state, country, internship_mode, "
        "hours_old, is_remote, job_count, jobs_json, scraped_at) "
        "VALUES ('Data Analyst', 'naukri', 'Bengaluru', 'Karnataka', 'in', 0, 168, "
        "0, 20, '[{\"url\":\"new\"}]', '2026-08-23T02:00:00') "
        "ON CONFLICT(role, site, city, state, country, internship_mode, hours_old, "
        "is_remote) DO UPDATE SET job_count = excluded.job_count, "
        "jobs_json = excluded.jobs_json, scraped_at = excluded.scraped_at"
    )
    conn.commit()
    cur.execute("SELECT COUNT(*) FROM job_cache")
    count = cur.fetchone()[0]
    assert count == 1, f"Expected 1 row (upserted), got {count}"
    cur.execute("SELECT job_count FROM job_cache")
    assert cur.fetchone()[0] == 20, "Upsert should have updated job_count to 20"
    print("Duplicate upsert works correctly")

    # 6. Verify remote vs non-remote are separate entries
    cur.execute(
        "INSERT INTO job_cache (role, site, city, state, country, internship_mode, "
        "hours_old, is_remote, job_count, jobs_json, scraped_at) "
        "VALUES ('Data Analyst', 'naukri', '', '', '', 0, 168, "
        "1, 3, '[{\"remote\":true}]', '2026-08-23T03:00:00') "
        "ON CONFLICT(role, site, city, state, country, internship_mode, hours_old, "
        "is_remote) DO UPDATE SET job_count = excluded.job_count"
    )
    conn.commit()
    cur.execute("SELECT COUNT(*) FROM job_cache")
    count = cur.fetchone()[0]
    assert count == 2, f"Expected 2 rows (remote + non-remote), got {count}"
    print("Remote vs non-remote stored as separate entries")

    conn.close()
    os.remove(old_db)
    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    test_migration()

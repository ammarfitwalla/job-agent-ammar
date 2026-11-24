import gzip
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import db  # noqa: E402


def _iso(days_ago: float) -> str:
    return (datetime.utcnow() - timedelta(days=days_ago)).isoformat()


def _job(i: int, days_ago: float = 1, **extra) -> dict:
    job = {
        "title": f"AI Engineer {i}",
        "company": "Acme",
        "url": f"https://acme.example/{i}",
        "description": "Build things.",
        "date_posted": _iso(days_ago),
        "tags": ["python"],
    }
    job.update(extra)
    return job


class JobArchiveTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp()
        cls.tmp = os.path.join(cls.tmpdir, "test.db")
        cls.export_dir = os.path.join(cls.tmpdir, "exports")
        cls._orig_path = db._DB_PATH
        db._DB_PATH = cls.tmp
        db.init_db()

    @classmethod
    def tearDownClass(cls):
        db._DB_PATH = cls._orig_path
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def tearDown(self):
        with db._get_conn() as (conn, cur):
            for table in ("job_cache", "job_archive", "archive_exports", "jobs", "sessions"):
                cur.execute(f"DELETE FROM {table}")
            conn.commit()

    # ── parse_posted_ts ──

    def test_parse_iso(self):
        dt = (datetime.utcnow() - timedelta(days=2)).replace(microsecond=0)
        self.assertEqual(db.parse_posted_ts(dt.isoformat()), db._dt_to_ts(dt))

    def test_parse_relative_against_anchor(self):
        anchor = (datetime.utcnow() - timedelta(days=20)).replace(microsecond=0)
        anchor_iso = anchor.isoformat()
        anchor_ts = db._dt_to_ts(anchor)
        self.assertEqual(db.parse_posted_ts("3 Days Ago", anchor_iso), anchor_ts - 3 * 86400)
        self.assertEqual(db.parse_posted_ts("30+ Days Ago", anchor_iso), anchor_ts - 30 * 86400)
        self.assertEqual(db.parse_posted_ts("2 Weeks Ago", anchor_iso), anchor_ts - 14 * 86400)
        self.assertEqual(db.parse_posted_ts("Just Now", anchor_iso), anchor_ts)

    def test_parse_empty_and_garbage_fall_back_to_anchor(self):
        anchor = (datetime.utcnow() - timedelta(days=7)).replace(microsecond=0)
        anchor_iso = anchor.isoformat()
        expected = db._dt_to_ts(anchor)
        self.assertEqual(db.parse_posted_ts("", anchor_iso), expected)
        self.assertEqual(db.parse_posted_ts("n/a", anchor_iso), expected)

    def test_parse_future_is_clamped(self):
        future = (datetime.utcnow() + timedelta(days=30)).isoformat()
        now_ts = db._dt_to_ts(datetime.utcnow())
        self.assertLessEqual(db.parse_posted_ts(future), now_ts + 1)

    # ── save_cache_entry preserves per-job freshness ──

    def test_save_cache_preserves_first_seen_and_posted_ts(self):
        db.save_cache_entry("AI", "linkedin", "", "", "us", 0, 24, [_job(1, 5)])
        with db._get_conn() as (conn, cur):
            cur.execute("SELECT jobs_json FROM job_cache")
            first = json.loads(cur.fetchone()[0])[0]

        db.save_cache_entry("AI", "linkedin", "", "", "us", 0, 24, [_job(1, 5)])
        with db._get_conn() as (conn, cur):
            cur.execute("SELECT jobs_json FROM job_cache")
            second = json.loads(cur.fetchone()[0])[0]

        self.assertEqual(second["first_seen"], first["first_seen"])
        self.assertEqual(second["posted_at_ts"], first["posted_at_ts"])

    def test_empty_date_uses_first_seen(self):
        job = _job(1)
        job["date_posted"] = ""
        db.save_cache_entry("AI", "linkedin", "", "", "us", 0, 24, [job])
        with db._get_conn() as (conn, cur):
            cur.execute("SELECT jobs_json FROM job_cache")
            saved = json.loads(cur.fetchone()[0])[0]

        first_seen_ts = db._dt_to_ts(datetime.fromisoformat(saved["first_seen"]))
        self.assertEqual(saved["posted_at_ts"], first_seen_ts)

    def test_real_date_replaces_unknown_posted_ts(self):
        job = _job(1)
        job["date_posted"] = ""
        db.save_cache_entry("AI", "linkedin", "", "", "us", 0, 24, [job])

        job["date_posted"] = _iso(2)
        db.save_cache_entry("AI", "linkedin", "", "", "us", 0, 24, [job])
        with db._get_conn() as (conn, cur):
            cur.execute("SELECT jobs_json FROM job_cache")
            saved = json.loads(cur.fetchone()[0])[0]

        expected = db.parse_posted_ts(job["date_posted"])
        self.assertEqual(saved["posted_at_ts"], expected)

    def test_posted_ts_is_not_refreshed_by_repost(self):
        db.save_cache_entry("AI", "linkedin", "", "", "us", 0, 24, [_job(1, 10)])
        with db._get_conn() as (conn, cur):
            cur.execute("SELECT jobs_json FROM job_cache")
            first = json.loads(cur.fetchone()[0])[0]

        db.save_cache_entry("AI", "linkedin", "", "", "us", 0, 24, [_job(1, 1)])
        with db._get_conn() as (conn, cur):
            cur.execute("SELECT jobs_json FROM job_cache")
            second = json.loads(cur.fetchone()[0])[0]

        self.assertEqual(second["posted_at_ts"], first["posted_at_ts"])

    # ── archive_stale_cache_jobs (Option B) ──

    def _seed_cache(self, fresh: int, old: int, role: str = "AI") -> None:
        jobs = [_job(i, 1) for i in range(fresh)] + [_job(1000 + i, 40) for i in range(old)]
        db.save_cache_entry(role, "linkedin", "", "", "us", 0, 24, jobs)

    def test_archive_evicts_old_when_enough_fresh(self):
        self._seed_cache(11, 3)
        stats = db.archive_stale_cache_jobs(fresh_days=14, min_jobs=10, batch_size=10)

        self.assertEqual(stats["archived"], 3)
        self.assertEqual(stats["rewritten"], 1)
        with db._get_conn() as (conn, cur):
            cur.execute("SELECT COUNT(*) FROM job_archive")
            self.assertEqual(cur.fetchone()[0], 3)
            cur.execute("SELECT job_count FROM job_cache")
            self.assertEqual(cur.fetchone()[0], 11)

    def test_archive_keeps_thin_entries(self):
        self._seed_cache(5, 3)
        stats = db.archive_stale_cache_jobs(fresh_days=14, min_jobs=10)

        self.assertEqual(stats["archived"], 0)
        self.assertEqual(stats["skipped_thin"], 1)
        with db._get_conn() as (conn, cur):
            cur.execute("SELECT COUNT(*) FROM job_cache")
            self.assertEqual(cur.fetchone()[0], 1)

    def test_archive_empties_fully_stale_entries(self):
        self._seed_cache(0, 3)
        stats = db.archive_stale_cache_jobs(fresh_days=14, min_jobs=10)

        self.assertEqual(stats["archived"], 3)
        self.assertEqual(stats["emptied"], 1)
        with db._get_conn() as (conn, cur):
            cur.execute("SELECT COUNT(*) FROM job_cache")
            self.assertEqual(cur.fetchone()[0], 0)

    def test_archive_dedupes_urls(self):
        self._seed_cache(11, 3)
        db.archive_stale_cache_jobs(fresh_days=14, min_jobs=10)
        # Re-running after a re-scrape should not duplicate archived URLs.
        self._seed_cache(11, 3)
        db.archive_stale_cache_jobs(fresh_days=14, min_jobs=10)
        with db._get_conn() as (conn, cur):
            cur.execute("SELECT COUNT(*) FROM job_archive")
            self.assertEqual(cur.fetchone()[0], 3)

    def test_archive_retains_jobs_without_url(self):
        job = _job(1, 40)
        job.pop("url")
        db.save_cache_entry("AI", "linkedin", "", "", "us", 0, 24, [job])

        stats = db.archive_stale_cache_jobs(fresh_days=14, min_jobs=10)

        self.assertEqual(stats["archived"], 0)
        self.assertEqual(stats["emptied"], 0)
        with db._get_conn() as (conn, cur):
            cur.execute("SELECT job_count FROM job_cache")
            self.assertEqual(cur.fetchone()[0], 1)

    # ── get_raw_jobs freshness filter ──

    def test_display_returns_fresh_only_when_enough(self):
        sid = "sess-fresh"
        db.create_session(sid)
        db.set_raw_jobs(sid, [_job(i, 1) for i in range(10)] + [_job(100 + i, 40) for i in range(3)])

        with patch.object(db, "_fresh_window_days", return_value=14), \
                patch.object(db, "_min_jobs", return_value=10):
            jobs = db.get_raw_jobs(sid)

        self.assertEqual(len(jobs), 10)
        cutoff = db._dt_to_ts(datetime.utcnow() - timedelta(days=14))
        self.assertTrue(all(j["posted_at_ts"] >= cutoff for j in jobs))

    def test_display_falls_back_to_all_when_thin(self):
        sid = "sess-thin"
        db.create_session(sid)
        db.set_raw_jobs(sid, [_job(i, 1) for i in range(5)] + [_job(100 + i, 40) for i in range(3)])

        with patch.object(db, "_fresh_window_days", return_value=14), \
                patch.object(db, "_min_jobs", return_value=10):
            jobs = db.get_raw_jobs(sid)

        self.assertEqual(len(jobs), 8)

    # ── export / clear / vacuum ──

    def test_export_writes_lossless_jsonl_gz(self):
        self._seed_cache(0, 3)
        db.archive_stale_cache_jobs(fresh_days=14, min_jobs=10)

        meta = db.export_job_archive(self.export_dir)
        self.assertEqual(meta["rows"], 3)
        self.assertTrue(os.path.isfile(meta["path"]))
        self.assertGreater(meta["size_bytes"], 0)

        with gzip.open(meta["path"], "rt", encoding="utf-8") as f:
            lines = [json.loads(line) for line in f if line.strip()]
        self.assertEqual(len(lines), 3)
        self.assertIn("url", lines[0])
        self.assertIn("description", lines[0])
        self.assertTrue(lines[0]["url"].startswith("https://acme.example/"))

    def test_export_sanitizes_nan(self):
        job = _job(1, 40, company_url=float("nan"))
        db.save_cache_entry("AI", "linkedin", "", "", "us", 0, 24, [job])
        db.archive_stale_cache_jobs(fresh_days=14, min_jobs=10)

        meta = db.export_job_archive(self.export_dir)
        with gzip.open(meta["path"], "rt", encoding="utf-8") as f:
            raw = f.read()
        self.assertNotIn("NaN", raw)
        self.assertEqual(len([line for line in raw.splitlines() if line.strip()]), 1)

    def test_list_exports_reports_size(self):
        self._seed_cache(0, 1)
        db.archive_stale_cache_jobs(fresh_days=14, min_jobs=10)

        with patch.object(db, "_archive_export_dir", return_value=self.export_dir):
            db.export_job_archive(self.export_dir)
            exports = db.list_archive_exports(limit=5)

        self.assertEqual(exports[0]["rows"], 1)
        self.assertGreater(exports[0]["size_bytes"], 0)

    def test_clear_requires_matching_export(self):
        self._seed_cache(0, 2)
        db.archive_stale_cache_jobs(fresh_days=14, min_jobs=10)

        refused = db.clear_job_archive()
        self.assertFalse(refused["ok"])

        meta = db.export_job_archive(self.export_dir)
        cleared = db.clear_job_archive(meta["id"])
        self.assertTrue(cleared["ok"])
        self.assertEqual(cleared["cleared"], 2)

        with db._get_conn() as (conn, cur):
            cur.execute("SELECT COUNT(*) FROM job_archive")
            self.assertEqual(cur.fetchone()[0], 0)

    def test_clear_refuses_when_archive_grew_after_export(self):
        self._seed_cache(0, 1)
        db.archive_stale_cache_jobs(fresh_days=14, min_jobs=10)
        meta = db.export_job_archive(self.export_dir)

        with db._get_conn() as (conn, cur):
            cur.execute(
                "INSERT INTO job_archive (url, title, archived_at) VALUES (?, ?, ?)",
                ("https://acme.example/late", "Late job", db._now()),
            )
            conn.commit()

        refused = db.clear_job_archive(meta["id"])
        self.assertFalse(refused["ok"])
        self.assertIn("export again", refused["error"])

    def test_vacuum_reclaims(self):
        self._seed_cache(0, 3)
        db.archive_stale_cache_jobs(fresh_days=14, min_jobs=10)
        meta = db.export_job_archive(self.export_dir)
        db.clear_job_archive(meta["id"])
        result = db.vacuum_db()
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(result["reclaimed_mb"], 0)


if __name__ == "__main__":
    unittest.main()

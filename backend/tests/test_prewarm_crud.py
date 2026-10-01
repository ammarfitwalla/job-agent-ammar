import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import db  # noqa: E402


class PrewarmCrudTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fd, cls.tmp = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        db._DB_PATH = cls.tmp
        db.init_db()

    @classmethod
    def tearDownClass(cls):
        try:
            os.remove(cls.tmp)
        except OSError:
            pass
        db._DB_PATH = os.path.join(os.path.dirname(os.path.abspath(db.__file__)), "job_agent.db")

    def tearDown(self):
        with db._write_lock:
            with db._get_conn() as (conn, cur):
                for t in ("prewarm_queue", "custom_prewarm"):
                    cur.execute(f"DELETE FROM {t}")
                conn.commit()


class TestPrewarmQueueCrud(PrewarmCrudTestCase):
    def test_add_combo_upserts_by_key(self):
        db.add_prewarm_combo("software engineer", "indeed", "", "ON", "Canada", 0, 168, 5, "admin")
        db.add_prewarm_combo("software engineer", "indeed", "", "ON", "Canada", 0, 168, 9, "admin")
        with db._get_conn() as (conn, cur):
            cur.execute("SELECT COUNT(*) AS n FROM prewarm_queue")
            self.assertEqual(cur.fetchone()["n"], 1)
            cur.execute("SELECT priority, source FROM prewarm_queue WHERE role = 'software engineer'")
            row = cur.fetchone()
        self.assertEqual(row["priority"], 9)
        self.assertEqual(row["source"], "admin")

    def test_get_queue_filters(self):
        db.add_prewarm_combo("python dev", "indeed", "", "", "", 0, 24, 3, "admin")
        db.add_prewarm_combo("react dev", "linkedin", "", "", "", 0, 168, 1, "user")
        rows = db.get_prewarm_queue()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["role"], "python dev")  # highest priority first

        by_src = db.get_prewarm_queue(source="user")
        self.assertEqual([r["role"] for r in by_src], ["react dev"])
        searched = db.get_prewarm_queue(search="python")
        self.assertEqual([r["role"] for r in searched], ["python dev"])

    def test_set_priority_and_delete_soft(self):
        db.add_prewarm_combo("devops", "indeed", "", "", "", 0, 168, 2)
        with db._get_conn() as (conn, cur):
            cur.execute("SELECT id FROM prewarm_queue WHERE role = 'devops'")
            combo_id = cur.fetchone()["id"]

        self.assertTrue(db.set_prewarm_queue_priority(combo_id, 42))
        with db._get_conn() as (conn, cur):
            cur.execute("SELECT priority FROM prewarm_queue WHERE id = ?", (combo_id,))
            self.assertEqual(cur.fetchone()["priority"], 42)

        self.assertTrue(db.delete_prewarm_combo_by_id(combo_id))
        self.assertEqual(db.get_prewarm_queue(), [])                       # hidden
        disabled = db.get_prewarm_queue(include_disabled=True)
        self.assertEqual(len(disabled), 1)
        self.assertTrue(disabled[0]["disabled"])

        # re-adding the same key re-enables it
        db.add_prewarm_combo("devops", "indeed", "", "", "", 0, 168, 7)
        rows = db.get_prewarm_queue()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["priority"], 7)

    def test_delete_unknown_id(self):
        self.assertFalse(db.delete_prewarm_combo_by_id(99999))

    def test_custom_prewarm_add_remove(self):
        db.upsert_custom_prewarm("backend engineer", "naukri", "", "Karnataka", "India", 0, 168)
        db.upsert_custom_prewarm("backend engineer", "naukri", "", "Karnataka", "India", 0, 168)
        db.increment_custom_prewarm_usage("backend engineer", "naukri", "", "Karnataka", "India", 0, 168)
        rows = db.get_custom_prewarm()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["usage_count"], 1)
        removed = db.remove_custom_prewarm("backend engineer", "naukri", "", "Karnataka", "India", 0, 168)
        self.assertTrue(removed)
        self.assertEqual(db.get_custom_prewarm(), [])


    def test_custom_prewarm_usage_increments_accumulate(self):
        key = ("backend engineer", "naukri", "", "Karnataka", "India", 0, 168)
        db.upsert_custom_prewarm(*key)
        for _ in range(5):
            db.increment_custom_prewarm_usage(*key)
        rows = db.get_custom_prewarm()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["usage_count"], 5)

    def test_gc_custom_prewarm_drops_old_singles_keeps_old_proven(self):
        def _pread_days_old(role, days_old):
            cutoff = (datetime.utcnow() - timedelta(days=days_old)).isoformat()
            with db._write_lock:
                with db._get_conn() as (conn, cur):
                    cur.execute("UPDATE custom_prewarm SET created_at = ? WHERE role = ?", (cutoff, role))
                    conn.commit()

        db.upsert_custom_prewarm("singleton", "naukri", "", "Karnataka", "India", 0, 168)
        db.upsert_custom_prewarm("borderline", "naukri", "", "Karnataka", "India", 0, 168)
        db.upsert_custom_prewarm("proven", "naukri", "", "Karnataka", "India", 0, 168)
        db.upsert_custom_prewarm("recent", "naukri", "", "Karnataka", "India", 0, 168)
        db.increment_custom_prewarm_usage("borderline", "naukri", "", "Karnataka", "India", 0, 168)
        for _ in range(2):
            db.increment_custom_prewarm_usage("proven", "naukri", "", "Karnataka", "India", 0, 168)

        _pread_days_old("singleton", 40)
        _pread_days_old("borderline", 40)
        _pread_days_old("proven", 40)
        _pread_days_old("recent", 5)

        db.gc_custom_prewarm(max_age_days=30)

        rows = {r["role"] for r in db.get_custom_prewarm()}
        self.assertNotIn("singleton", rows)   # old + usage 0 (< 2) -> deleted
        self.assertNotIn("borderline", rows)  # old + usage 1 (< 2) -> deleted
        self.assertIn("proven", rows)         # old + usage 2 (>= 2) -> kept
        self.assertIn("recent", rows)         # new regardless of usage -> grace window

    def test_gc_custom_prewarm_min_uses_override(self):
        key = ("abandoned", "naukri", "", "Karnataka", "India", 0, 168)
        db.upsert_custom_prewarm(*key)
        for _ in range(2):
            db.increment_custom_prewarm_usage(*key)
        cutoff = (datetime.utcnow() - timedelta(days=40)).isoformat()
        with db._write_lock:
            with db._get_conn() as (conn, cur):
                cur.execute("UPDATE custom_prewarm SET created_at = ? WHERE role = 'abandoned'", (cutoff,))
                conn.commit()

        db.gc_custom_prewarm(max_age_days=30, min_uses=3)

        rows = {r["role"] for r in db.get_custom_prewarm()}
        self.assertNotIn("abandoned", rows)   # old + usage 2 < min_uses 3 -> deleted

    def test_gc_custom_prewarm_upsert_refreshes_created_at(self):
        db.upsert_custom_prewarm("backend engineer", "naukri", "", "Karnataka", "India", 0, 168)
        old = (datetime.utcnow() - timedelta(days=40)).isoformat()
        with db._write_lock:
            with db._get_conn() as (conn, cur):
                cur.execute("UPDATE custom_prewarm SET created_at = ? WHERE role = 'backend engineer'", (old,))
                conn.commit()

        db.upsert_custom_prewarm("backend engineer", "naukri", "", "Karnataka", "India", 0, 168)
        db.gc_custom_prewarm(max_age_days=30)
        rows = db.get_custom_prewarm()
        self.assertEqual(len(rows), 1)
        self.assertLess(old, rows[0]["created_at"])


if __name__ == "__main__":
    unittest.main()
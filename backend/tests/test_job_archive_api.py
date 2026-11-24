"""HTTP-level tests for the admin old-job archive endpoints.

Covers route registration, auth gating, the export → download → clear → vacuum
flow, and the "nothing to export" path. DB logic itself is covered by
test_job_archive.py.
"""
import gzip
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

os.environ["JWT_ALLOW_DEV_SECRET"] = "1"

import db  # noqa: E402
from utils.jwt import create_token  # noqa: E402


def _iso(days_ago: float) -> str:
    return (datetime.utcnow() - timedelta(days=days_ago)).isoformat()


def _job(i: int, days_ago: float) -> dict:
    return {
        "title": f"AI Engineer {i}",
        "company": "Acme",
        "url": f"https://acme.example/{i}",
        "description": "Build things.",
        "date_posted": _iso(days_ago),
        "tags": ["python"],
    }


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


ADMIN = "archive-admin@example.com"
USER = "archive-user@example.com"


class JobArchiveApiTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fd, cls.tmp = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        cls._orig_path = db._DB_PATH
        db._DB_PATH = cls.tmp
        db.init_db()
        db.create_user(ADMIN, "Archive Admin")
        db.create_user(USER, "Archive User")
        db.grant_admin(ADMIN, "test")

        cls.export_dir = tempfile.mkdtemp(prefix="archive_api_exports_")
        cls._orig_export_dir = db._archive_export_dir
        db._archive_export_dir = lambda: cls.export_dir

        cls.admin_token = create_token(ADMIN)
        cls.user_token = create_token(USER)

        from fastapi.testclient import TestClient
        from api.main import app

        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        db._archive_export_dir = cls._orig_export_dir
        db._DB_PATH = cls._orig_path
        shutil.rmtree(cls.export_dir, ignore_errors=True)
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(cls.tmp + suffix)
            except OSError:
                pass

    def tearDown(self):
        with db._get_conn() as (conn, cur):
            for table in ("job_cache", "job_archive", "archive_exports", "sessions"):
                cur.execute(f"DELETE FROM {table}")
            conn.commit()
        for name in os.listdir(self.export_dir):
            try:
                os.remove(os.path.join(self.export_dir, name))
            except OSError:
                pass

    def _seed_archive(self, fresh: int = 0, old: int = 2) -> None:
        jobs = [_job(i, 1) for i in range(fresh)] + [_job(1000 + i, 40) for i in range(old)]
        db.save_cache_entry("AI", "linkedin", "", "", "us", 0, 24, jobs)
        db.archive_stale_cache_jobs(fresh_days=14, min_jobs=10)

    # ── auth gating ──

    def test_info_requires_token(self):
        r = self.client.get("/api/admin/job-archive/info")
        self.assertEqual(r.status_code, 401)

    def test_non_admin_forbidden(self):
        r = self.client.get("/api/admin/job-archive/info", headers=_auth(self.user_token))
        self.assertEqual(r.status_code, 403)

    def test_clear_and_vacuum_are_admin_gated(self):
        for path in ("/api/admin/job-archive/clear", "/api/admin/job-archive/vacuum"):
            r = self.client.post(path, headers=_auth(self.user_token))
            self.assertEqual(r.status_code, 403, path)

    # ── full flow ──

    def test_export_download_clear_vacuum(self):
        self._seed_archive(fresh=0, old=2)

        info = self.client.get("/api/admin/job-archive/info", headers=_auth(self.admin_token))
        self.assertEqual(info.status_code, 200)
        body = info.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["archived_jobs"], 2)

        export = self.client.post("/api/admin/job-archive/export", headers=_auth(self.admin_token))
        self.assertEqual(export.status_code, 200)
        meta = export.json()
        self.assertTrue(meta["ok"], meta)
        self.assertEqual(meta["rows"], 2)
        self.assertGreater(meta["size_bytes"], 0)
        self.assertTrue(meta["download_url"].endswith(f"/{meta['id']}"))

        download = self.client.get(meta["download_url"], headers=_auth(self.admin_token))
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.headers.get("content-type"), "application/gzip")
        lines = gzip.decompress(download.content).decode("utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0])["company"], "Acme")

        listed = self.client.get("/api/admin/job-archive/exports", headers=_auth(self.admin_token))
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["exports"][0]["id"], meta["id"])
        self.assertGreater(listed.json()["exports"][0]["size_bytes"], 0)

        cleared = self.client.post("/api/admin/job-archive/clear", headers=_auth(self.admin_token))
        self.assertEqual(cleared.status_code, 200)
        self.assertTrue(cleared.json()["ok"])
        self.assertEqual(cleared.json()["cleared"], 2)

        vacuum = self.client.post("/api/admin/job-archive/vacuum", headers=_auth(self.admin_token))
        self.assertEqual(vacuum.status_code, 200)
        self.assertTrue(vacuum.json()["ok"])

        after = self.client.get("/api/admin/job-archive/info", headers=_auth(self.admin_token)).json()
        self.assertEqual(after["archived_jobs"], 0)
        self.assertEqual(after["cache_rows"], 0)

    def test_export_empty_archive_is_rejected(self):
        r = self.client.post("/api/admin/job-archive/export", headers=_auth(self.admin_token))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["ok"])

    def test_clear_without_export_is_rejected(self):
        self._seed_archive(fresh=0, old=1)
        r = self.client.post("/api/admin/job-archive/clear", headers=_auth(self.admin_token))
        self.assertEqual(r.status_code, 409)
        self.assertFalse(r.json()["ok"])

    def test_download_missing_export_is_404(self):
        r = self.client.get("/api/admin/job-archive/download/999999", headers=_auth(self.admin_token))
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()

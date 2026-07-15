import unittest
import time
import sqlite3
import sys
import os
from unittest.mock import patch
from copy import deepcopy

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


import tempfile

_TEST_DB_INIT = False
_TEST_DB_PATH = None


def _init_test_db():
    global _TEST_DB_INIT, _TEST_DB_PATH
    if _TEST_DB_INIT:
        return
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    _TEST_DB_PATH = tmp.name
    conn = sqlite3.connect(_TEST_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            email TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            company TEXT DEFAULT '',
            position TEXT DEFAULT '',
            linkedin_url TEXT DEFAULT '',
            referral_credits INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS verification_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            code TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            used INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_vcodes_email ON verification_codes(email);
        CREATE TABLE IF NOT EXISTS referral_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_email TEXT NOT NULL,
            to_email TEXT NOT NULL,
            job_url TEXT DEFAULT '',
            job_title TEXT DEFAULT '',
            company TEXT DEFAULT '',
            match_score INTEGER DEFAULT 0,
            message TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            credit_awarded INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ref_req_from ON referral_requests(from_email);
        CREATE INDEX IF NOT EXISTS idx_ref_req_to ON referral_requests(to_email, status);
        CREATE TABLE IF NOT EXISTS saved_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            company TEXT DEFAULT '',
            url TEXT DEFAULT '',
            location TEXT DEFAULT '',
            salary TEXT DEFAULT '',
            total_score INTEGER DEFAULT 0,
            ai_score INTEGER DEFAULT 0,
            keyword_score INTEGER DEFAULT 0,
            reason TEXT DEFAULT '',
            experience_level TEXT DEFAULT '',
            tags TEXT DEFAULT '[]',
            site TEXT DEFAULT '',
            application_status TEXT DEFAULT 'saved',
            saved_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (user_email) REFERENCES users(email),
            UNIQUE(user_email, url)
        );
        CREATE INDEX IF NOT EXISTS idx_saved_email ON saved_jobs(user_email);
        CREATE INDEX IF NOT EXISTS idx_saved_status ON saved_jobs(user_email, application_status);
        CREATE TABLE IF NOT EXISTS custom_companies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL
        );
    """)
    conn.executescript("PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;")
    conn.close()
    _TEST_DB_INIT = True


def _fresh_conn():
    conn = sqlite3.connect(_TEST_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript("PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;")
    return conn, conn.cursor()


def _make_conn_patch():
    def fake_get_conn():
        return _fresh_conn()
    return fake_get_conn


class TestIntegrationAuthFlow(unittest.TestCase):
    def setUp(self):
        _init_test_db()
        self._conn_patcher = patch("db._get_conn", _make_conn_patch())
        self._conn_patcher.start()

        self._dev_mode_patcher = patch("api.routes.auth.DEV_MODE", True)
        self._dev_mode_patcher.start()

        from utils.rate_limiter import _limits
        _limits.clear()

        from fastapi.testclient import TestClient
        from api.main import app
        self.client = TestClient(app)

    def tearDown(self):
        self._conn_patcher.stop()
        self._dev_mode_patcher.stop()

    def _send_code(self, email):
        return self.client.post("/api/auth/send-code", json={"email": email})

    def _verify_code(self, email, code="123456"):
        return self.client.post("/api/auth/verify-code", json={"email": email, "code": code})

    def _register(self, email, name, company="", position="", linkedin_url=""):
        return self.client.post("/api/auth/register", json={
            "email": email, "name": name, "company": company,
            "position": position, "linkedin_url": linkedin_url,
        })

    def test_01_full_auth_flow(self):
        email = "testuser@example.com"
        r = self._send_code(email)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["ok"])

        r = self._verify_code(email)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["user"]["email"], email)
        self.assertEqual(data["user"]["name"], "testuser")

        r = self._register(email, "Test User", "Google", "Engineer", "https://linkedin.com/in/test")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["user"]["name"], "Test User")
        self.assertEqual(data["user"]["company"], "Google")

    def test_02_verify_creates_user_auto(self):
        email = "newauto@example.com"
        r = self._verify_code(email)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["user"]["email"], email)
        self.assertEqual(data["user"]["company"], "")

    def test_03_register_updates_existing_user(self):
        email = "update@example.com"
        self._verify_code(email)
        r = self._register(email, "Updated Name", "Meta", "SDE")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["user"]["name"], "Updated Name")
        self.assertEqual(data["user"]["company"], "Meta")
        self.assertEqual(data["user"]["position"], "SDE")

    def test_04_rate_limiting_on_send_code(self):
        from utils.rate_limiter import _limits
        _limits.clear()
        email = "ratelimit@example.com"
        for i in range(3):
            r = self._send_code(email)
            self.assertEqual(r.status_code, 200)
        r = self._send_code(email)
        self.assertEqual(r.status_code, 429)

    def test_05_rate_limiting_on_verify_code(self):
        from utils.rate_limiter import _limits
        _limits.clear()
        email = "ratelimitverify@example.com"
        for i in range(5):
            r = self._verify_code(email, "000000")
        r = self._verify_code(email, "000000")
        self.assertEqual(r.status_code, 429)


class TestIntegrationProfileFlow(unittest.TestCase):
    def setUp(self):
        _init_test_db()
        self._conn_patcher = patch("db._get_conn", _make_conn_patch())
        self._conn_patcher.start()

        self._dev_mode_patcher = patch("api.routes.auth.DEV_MODE", True)
        self._dev_mode_patcher.start()

        from utils.rate_limiter import _limits
        _limits.clear()

        from fastapi.testclient import TestClient
        from api.main import app
        self.client = TestClient(app)

        self.email = "profiletest@example.com"
        self.client.post("/api/auth/verify-code", json={"email": self.email, "code": "123456"})
        self.client.post("/api/auth/register", json={
            "email": self.email, "name": "Profile User", "company": "Acme",
            "position": "Developer", "linkedin_url": "https://linkedin.com/in/profile",
        })

    def tearDown(self):
        self._conn_patcher.stop()
        self._dev_mode_patcher.stop()

    def test_01_get_profile(self):
        r = self.client.get(f"/api/profile?email={self.email}")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["email"], self.email)
        self.assertEqual(data["name"], "Profile User")
        self.assertEqual(data["company"], "Acme")
        self.assertEqual(data["position"], "Developer")
        self.assertEqual(data["linkedin_url"], "https://linkedin.com/in/profile")
        self.assertIn("created_at", data)
        self.assertIn("referral_credits", data)
        self.assertIn("status_counts", data)

    def test_02_get_profile_nonexistent(self):
        r = self.client.get("/api/profile?email=nobody@example.com")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("error", data)

    def test_03_get_profile_no_email(self):
        r = self.client.get("/api/profile?email=")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("error", data)

    def test_04_update_profile(self):
        r = self.client.put("/api/profile", json={
            "email": self.email, "name": "Updated Profile",
            "company": "Google", "position": "Senior Dev",
            "linkedin_url": "https://linkedin.com/in/updated",
        })
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["user"]["name"], "Updated Profile")
        self.assertEqual(data["user"]["company"], "Google")
        self.assertEqual(data["user"]["position"], "Senior Dev")

    def test_05_update_name_only(self):
        r = self.client.put("/api/profile/name", json={"email": self.email, "name": "Just Name"})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["name"], "Just Name")

    def test_06_profile_persists_after_refresh(self):
        r = self.client.put("/api/profile", json={
            "email": self.email, "name": "After Refresh",
            "company": "Microsoft", "position": "Engineer",
        })
        self.assertTrue(r.json()["ok"])

        r2 = self.client.get(f"/api/profile?email={self.email}")
        self.assertEqual(r2.status_code, 200)
        data = r2.json()
        self.assertEqual(data["name"], "After Refresh")
        self.assertEqual(data["company"], "Microsoft")
        self.assertEqual(data["position"], "Engineer")


class TestIntegrationReferralFlow(unittest.TestCase):
    def setUp(self):
        _init_test_db()
        conn, cur = _fresh_conn()
        cur.execute("DELETE FROM referral_requests")
        conn.commit()
        conn.close()

        self._conn_patcher = patch("db._get_conn", _make_conn_patch())
        self._conn_patcher.start()

        self._dev_mode_patcher = patch("api.routes.auth.DEV_MODE", True)
        self._dev_mode_patcher.start()

        from utils.rate_limiter import _limits
        _limits.clear()

        from fastapi.testclient import TestClient
        from api.main import app
        self.client = TestClient(app)

        self.from_email = "referrer@example.com"
        self.to_email = "referee@example.com"
        self.job_url = "https://example.com/job/123"
        self.job_title = "Software Engineer"
        self.company = "Google"
        self.match_score = 85
        self.message = "Great fit!"

        self.client.post("/api/auth/verify-code", json={"email": self.from_email, "code": "123456"})
        self.client.post("/api/auth/register", json={
            "email": self.from_email, "name": "Referrer", "company": "Meta",
        })
        self.client.post("/api/auth/verify-code", json={"email": self.to_email, "code": "123456"})
        self.client.post("/api/auth/register", json={
            "email": self.to_email, "name": "Referee", "company": "Acme",
        })

    def tearDown(self):
        self._conn_patcher.stop()
        self._dev_mode_patcher.stop()

    def _create_referral(self, from_email=None, to_email=None, job_url=None):
        return self.client.post("/api/referrals/request", json={
            "from_email": from_email or self.from_email,
            "to_email": to_email or self.to_email,
            "job_url": job_url or self.job_url,
            "job_title": self.job_title,
            "company": self.company,
            "match_score": self.match_score,
            "message": self.message,
        })

    def test_01_create_referral(self):
        r = self._create_referral()
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["ok"])
        self.assertIn("id", data)

    def test_02_self_referral_blocked(self):
        r = self._create_referral(from_email=self.from_email, to_email=self.from_email)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertFalse(data["ok"])
        self.assertIn("yourself", data["error"].lower())

    def test_03_duplicate_referral_blocked(self):
        self._create_referral()
        r = self._create_referral()
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertFalse(data["ok"])
        self.assertIn("already have a pending", data["error"].lower())

    def test_04_get_incoming(self):
        self._create_referral()
        r = self.client.get(f"/api/referrals/incoming?email={self.to_email}")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertGreaterEqual(len(data.get("requests", [])), 1)
        self.assertEqual(data["requests"][0]["from_email"], self.from_email)

    def test_05_get_outgoing(self):
        self._create_referral()
        r = self.client.get(f"/api/referrals/outgoing?email={self.from_email}")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertGreaterEqual(len(data.get("requests", [])), 1)
        self.assertEqual(data["requests"][0]["to_email"], self.to_email)

    def test_06_accept_referral(self):
        self._create_referral()
        outgoing = self.client.get(f"/api/referrals/outgoing?email={self.from_email}").json()
        rid = outgoing["requests"][0]["id"]
        r = self.client.put(f"/api/referrals/{rid}/accept", json={"email": self.to_email})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["ok"])
        self.assertIn("contact", data)

    def test_07_complete_referral(self):
        self._create_referral()
        outgoing = self.client.get(f"/api/referrals/outgoing?email={self.from_email}").json()
        rid = outgoing["requests"][0]["id"]
        self.client.put(f"/api/referrals/{rid}/accept", json={"email": self.to_email})
        r = self.client.put(f"/api/referrals/{rid}/complete", json={"email": self.to_email})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["ok"])
        self.assertIn("credits_earned", data)

    def test_08_withdraw_referral(self):
        self._create_referral()
        outgoing = self.client.get(f"/api/referrals/outgoing?email={self.from_email}").json()
        rid = outgoing["requests"][0]["id"]
        r = self.client.put(f"/api/referrals/{rid}/withdraw", json={"email": self.from_email})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["ok"])

    def test_09_withdraw_only_by_sender(self):
        self._create_referral()
        outgoing = self.client.get(f"/api/referrals/outgoing?email={self.from_email}").json()
        rid = outgoing["requests"][0]["id"]
        r = self.client.put(f"/api/referrals/{rid}/withdraw", json={"email": self.to_email})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertFalse(data["ok"])

    def test_10_remaining_count(self):
        r = self.client.get(f"/api/referrals/remaining?email={self.from_email}")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["remaining"], 3)
        self.assertEqual(data["limit"], 3)

        self._create_referral()
        r = self.client.get(f"/api/referrals/remaining?email={self.from_email}")
        data = r.json()
        self.assertEqual(data["remaining"], 2)

    def test_11_monthly_limit(self):
        for i in range(3):
            ref_email = f"ref{i}@example.com"
            self.client.post("/api/auth/verify-code", json={"email": ref_email, "code": "123456"})
            self.client.post("/api/auth/register", json={"email": ref_email, "name": f"Ref{i}"})
            r = self._create_referral(to_email=ref_email, job_url=f"https://example.com/job/{i}")
            self.assertTrue(r.json()["ok"])

        self.client.post("/api/auth/verify-code", json={"email": "overflow@example.com", "code": "123456"})
        self.client.post("/api/auth/register", json={"email": "overflow@example.com", "name": "Overflow"})
        r = self._create_referral(to_email="overflow@example.com", job_url="https://example.com/job/overflow")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertFalse(data["ok"])
        self.assertIn("limit reached", data["error"].lower())
        self.assertEqual(data["remaining"], 0)

    def test_12_decline_referral(self):
        self._create_referral()
        outgoing = self.client.get(f"/api/referrals/outgoing?email={self.from_email}").json()
        rid = outgoing["requests"][0]["id"]
        r = self.client.put(f"/api/referrals/{rid}/decline", json={"email": self.to_email})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["ok"])


class TestIntegrationCompanyHarvest(unittest.TestCase):
    def setUp(self):
        _init_test_db()
        self._conn_patcher = patch("db._get_conn", _make_conn_patch())
        self._conn_patcher.start()

        self._companies_patcher = patch("config.COMPANIES", ["Google", "Meta"])
        self._companies_patcher.start()

        from utils.rate_limiter import _limits
        _limits.clear()

    def tearDown(self):
        self._conn_patcher.stop()
        self._companies_patcher.stop()

    def _get_rows(self, sql):
        conn, cur = _fresh_conn()
        cur.execute(sql)
        rows = [r[0] for r in cur.fetchall()]
        conn.close()
        return rows

    def test_harvest_new_companies(self):
        from api.routes.scrape import _harvest_companies
        jobs = [
            {"company": "StartupCo"},
            {"company": "NewBiz"},
            {"company": "  WhitespaceCo  "},
        ]
        _harvest_companies(jobs)
        rows = self._get_rows("SELECT name FROM custom_companies ORDER BY name")
        self.assertIn("StartupCo", rows)
        self.assertIn("NewBiz", rows)
        self.assertIn("WhitespaceCo", rows)

    def test_skips_hardcoded_companies(self):
        from api.routes.scrape import _harvest_companies
        jobs = [{"company": "Google"}, {"company": "Meta"}, {"company": "NewCo"}]
        _harvest_companies(jobs)
        rows = self._get_rows("SELECT name FROM custom_companies")
        self.assertNotIn("Google", rows)
        self.assertNotIn("Meta", rows)
        self.assertIn("NewCo", rows)

    def test_empty_company_skipped(self):
        from api.routes.scrape import _harvest_companies
        jobs = [{"company": ""}, {"company": "ValidCo"}]
        _harvest_companies(jobs)
        rows = self._get_rows("SELECT name FROM custom_companies")
        self.assertEqual(rows, ["ValidCo"])


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        if _TEST_DB_PATH and os.path.exists(_TEST_DB_PATH):
            try:
                os.unlink(_TEST_DB_PATH)
            except Exception:
                pass

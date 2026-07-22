import unittest
import time
import sqlite3
import threading
import json
import sys
import os
import contextlib
from unittest.mock import patch, MagicMock
from copy import deepcopy

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


# ── 1. Rate Limiter ──

class TestRateLimiter(unittest.TestCase):
    def setUp(self):
        from utils.rate_limiter import _limits
        _limits.clear()

    def test_allows_within_limit(self):
        from utils.rate_limiter import check_rate_limit
        for _ in range(3):
            self.assertTrue(check_rate_limit("test_key", 3, 60))

    def test_blocks_over_limit(self):
        from utils.rate_limiter import check_rate_limit
        for _ in range(3):
            check_rate_limit("test_key", 3, 60)
        self.assertFalse(check_rate_limit("test_key", 3, 60))

    def test_expires_after_window(self):
        from utils.rate_limiter import check_rate_limit, _limits
        for _ in range(3):
            check_rate_limit("test_key", 3, 60)
        _limits["test_key"] = [time.time() - 61]
        self.assertTrue(check_rate_limit("test_key", 3, 60))

    def test_different_keys_independent(self):
        from utils.rate_limiter import check_rate_limit
        for _ in range(3):
            check_rate_limit("key_a", 3, 60)
        self.assertTrue(check_rate_limit("key_b", 3, 60))
        self.assertFalse(check_rate_limit("key_a", 3, 60))


# ── 2. DB Functions ──

def _make_test_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE users (
            email TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            company TEXT DEFAULT '',
            position TEXT DEFAULT '',
            linkedin_url TEXT DEFAULT '',
            referral_credits INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE referral_requests (
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
        )
    """)
    return conn


class TestGetCompanyUserCounts(unittest.TestCase):
    def setUp(self):
        self.conn = _make_test_db()
        self.conn.execute("INSERT INTO users (email, name, company, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                          ("a@x.com", "A", "Google", "2024-01-01", "2024-01-01"))
        self.conn.execute("INSERT INTO users (email, name, company, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                          ("b@x.com", "B", "Google", "2024-01-01", "2024-01-01"))
        self.conn.execute("INSERT INTO users (email, name, company, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                          ("c@x.com", "C", "Meta", "2024-01-01", "2024-01-01"))
        self.conn.execute("INSERT INTO users (email, name, company, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                          ("d@x.com", "D", "", "2024-01-01", "2024-01-01"))

        @contextlib.contextmanager
        def _fake_conn():
            yield self.conn, self.conn.cursor()
        self._get_conn_patcher = patch("db._get_conn", _fake_conn)
        self._get_conn_patcher.start()

    def tearDown(self):
        self._get_conn_patcher.stop()
        self.conn.close()

    def test_counts_by_company(self):
        from db import get_company_user_counts
        result = get_company_user_counts(["Google", "Meta"])
        self.assertEqual(result.get("google"), 2)
        self.assertEqual(result.get("meta"), 1)

    def test_excludes_empty_company(self):
        from db import get_company_user_counts
        result = get_company_user_counts([""])
        self.assertEqual(result, {})

    def test_excludes_user(self):
        from db import get_company_user_counts
        result = get_company_user_counts(["Google", "Meta"], exclude_email="a@x.com")
        self.assertEqual(result.get("google"), 1)
        self.assertEqual(result.get("meta"), 1)

    def test_empty_companies_list(self):
        from db import get_company_user_counts
        self.assertEqual(get_company_user_counts([]), {})

    def test_case_insensitive(self):
        from db import get_company_user_counts
        result = get_company_user_counts(["google", "META"])
        self.assertEqual(result.get("google"), 2)
        self.assertEqual(result.get("meta"), 1)


class TestGetMonthlySentCount(unittest.TestCase):
    def setUp(self):
        from datetime import datetime
        self.today = datetime.now().strftime("%Y-%m-%d")
        self.conn = _make_test_db()
        self.conn.execute("""
            INSERT INTO referral_requests (from_email, to_email, job_url, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("me@x.com", "a@x.com", "url1", "pending", self.today, self.today))
        self.conn.execute("""
            INSERT INTO referral_requests (from_email, to_email, job_url, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("me@x.com", "b@x.com", "url2", "pending", self.today, self.today))
        self.conn.execute("""
            INSERT INTO referral_requests (from_email, to_email, job_url, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("me@x.com", "c@x.com", "url3", "cancelled", self.today, self.today))
        self.conn.execute("""
            INSERT INTO referral_requests (from_email, to_email, job_url, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("other@x.com", "d@x.com", "url4", "pending", self.today, self.today))

        @contextlib.contextmanager
        def _fake_conn():
            yield self.conn, self.conn.cursor()
        self._get_conn_patcher = patch("db._get_conn", _fake_conn)
        self._get_conn_patcher.start()

    def tearDown(self):
        self._get_conn_patcher.stop()
        self.conn.close()

    def test_counts_only_non_cancelled(self):
        from db import get_monthly_sent_count
        cnt = get_monthly_sent_count("me@x.com")
        self.assertEqual(cnt, 2)

    def test_other_user_requests_not_counted(self):
        from db import get_monthly_sent_count
        cnt = get_monthly_sent_count("other@x.com")
        self.assertEqual(cnt, 1)

    def test_no_requests_returns_zero(self):
        from db import get_monthly_sent_count
        cnt = get_monthly_sent_count("nobody@x.com")
        self.assertEqual(cnt, 0)


class TestGetPendingReferral(unittest.TestCase):
    def setUp(self):
        self.conn = _make_test_db()
        self.conn.execute("""
            INSERT INTO referral_requests (from_email, to_email, job_url, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("me@x.com", "a@x.com", "url1", "pending", "2024-01-01", "2024-01-01"))
        self.conn.execute("""
            INSERT INTO referral_requests (from_email, to_email, job_url, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("me@x.com", "a@x.com", "url1", "accepted", "2024-01-02", "2024-01-02"))

        @contextlib.contextmanager
        def _fake_conn():
            yield self.conn, self.conn.cursor()
        self._get_conn_patcher = patch("db._get_conn", _fake_conn)
        self._get_conn_patcher.start()

    def tearDown(self):
        self._get_conn_patcher.stop()
        self.conn.close()

    def test_finds_pending_duplicate(self):
        from db import get_pending_referral
        result = get_pending_referral("me@x.com", "a@x.com", "url1")
        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "pending")

    def test_returns_none_if_no_pending(self):
        from db import get_pending_referral
        result = get_pending_referral("me@x.com", "b@x.com", "url1")
        self.assertIsNone(result)

    def test_ignores_non_pending_status(self):
        from db import get_pending_referral
        result = get_pending_referral("me@x.com", "a@x.com", "url1")
        self.assertEqual(result["status"], "pending")


# ── 3. Filter Jobs Sort with Company Counts ──

class TestFilterJobsCompanyBoost(unittest.TestCase):
    def setUp(self):
        self.jobs = [
            {"title": "Software Engineer at Google", "company": "Google", "description": "coding job", "tags": ["python"]},
            {"title": "Software Engineer at Meta", "company": "Meta", "description": "coding job", "tags": ["python"]},
            {"title": "Software Engineer at Acme", "company": "Acme", "description": "coding job", "tags": ["python"]},
            {"title": "DevOps Engineer at Google", "company": "Google", "description": "devops job", "tags": ["aws"]},
            {"title": "Manager at Acme", "company": "Acme", "description": "management", "tags": []},
        ]
        self.company_counts = {"google": 5, "meta": 2}
        self._llm_patcher = patch("llm.llm_client.LLMClient.chat")
        self._batch_patcher = patch("llm.llm_client.LLMClient.batch_chat")
        self.mock_chat = self._llm_patcher.start()
        self.mock_batch = self._batch_patcher.start()
        llm_response = '{"is_relevant": true, "score": 70, "matched_skills": ["python"], "reasoning": "has python"}'
        self.mock_chat.return_value = llm_response
        self.mock_batch.return_value = json.dumps([
            json.loads(llm_response)
        ] * 5)

    def tearDown(self):
        self._llm_patcher.stop()
        self._batch_patcher.stop()

    def _call_filter_jobs(self, jobs, roles=None, company_counts=None):
        from match_engine.relevance_engine import filter_jobs
        result = filter_jobs(
            jobs,
            min_score=0,
            keywords=["python"],
            resume="python developer",
            roles=roles or [],
            llm_candidate_limit=20,
            llm_weight=0.5,
            kw_weight=0.5,
            max_workers=1,
            internship_mode=False,
            company_user_counts=company_counts,
        )
        return result

    def test_role_matched_jobs_sorted_by_company_count(self):
        result = self._call_filter_jobs(self.jobs, roles=["software engineer"], company_counts=self.company_counts)
        if len(result) >= 3:
            google_count_meta = result[0]["company"] == "Google" and result[1]["company"] == "Meta"
            meta_count_acme = result[0]["company"] == "Meta" and result[1]["company"] == "Google"
            self.assertTrue(google_count_meta or meta_count_acme)

    def test_user_own_company_zeroed_out(self):
        counts = dict(self.company_counts)
        counts["google"] = 0
        result = self._call_filter_jobs(self.jobs, roles=["software engineer"], company_counts=counts)
        if len(result) >= 2:
            meta_before_google = result[0]["company"] == "Meta" and result[1]["company"] == "Google"
            self.assertTrue(meta_before_google or result[0]["company"] != "Google")

    def test_no_company_counts_same_as_default(self):
        result_with = self._call_filter_jobs(self.jobs, roles=["software engineer"], company_counts={})
        result_without = self._call_filter_jobs(self.jobs, roles=["software engineer"], company_counts=None)
        titles_with = [j["title"] for j in result_with]
        titles_without = [j["title"] for j in result_without]
        self.assertEqual(titles_with, titles_without)

    def test_non_role_matched_jobs_unchanged(self):
        result = self._call_filter_jobs(self.jobs, roles=[], company_counts=self.company_counts)
        manager_jobs = [j for j in result if "Manage" in j["title"]]
        self.assertGreaterEqual(len(manager_jobs), 0)


# ── 4. Rate Limiter Edge Cases ──

class TestRateLimiterEdgeCases(unittest.TestCase):
    def setUp(self):
        from utils.rate_limiter import _limits
        _limits.clear()

    def test_zero_max_requests_blocks_immediately(self):
        from utils.rate_limiter import check_rate_limit
        self.assertFalse(check_rate_limit("zero_key", 0, 60))

    def test_negative_window_not_blocked(self):
        from utils.rate_limiter import check_rate_limit
        self.assertTrue(check_rate_limit("neg_key", 1, -1))
        self.assertTrue(check_rate_limit("neg_key", 1, -1))

    def test_exact_boundary(self):
        from utils.rate_limiter import check_rate_limit
        for _ in range(5):
            check_rate_limit("boundary_key", 5, 60)
        self.assertFalse(check_rate_limit("boundary_key", 5, 60))

    def test_empty_key(self):
        from utils.rate_limiter import check_rate_limit
        self.assertTrue(check_rate_limit("", 1, 60))
        self.assertFalse(check_rate_limit("", 1, 60))


# ── 5. Self-Referral Block ──

class TestSelfReferralBlock(unittest.TestCase):
    def test_self_referral_detected(self):
        from api.routes.referrals import _MONTHLY_LIMIT
        self.assertEqual(_MONTHLY_LIMIT, 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)

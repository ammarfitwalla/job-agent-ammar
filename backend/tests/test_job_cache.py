import json
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import db  # noqa: E402


class CacheDBTestCase(unittest.TestCase):
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
        db.gc_job_cache(max_age_hours=0, max_entries=0)
        with db._get_conn() as (conn, cur):
            cur.execute("DELETE FROM prewarm_queue")
            conn.commit()


def _jobs(n, tag=""):
    return [{"title": f"AI Engineer {tag}{i}", "company": "Acme", "url": f"https://acme.example/{tag}{i}",
             "description": "Building ML systems", "tags": []} for i in range(n)]


# ── job_cache ──

class TestJobCache(CacheDBTestCase):
    def test_save_and_get_fresh(self):
        db.save_cache_entry("AI Engineer", "indeed", "", "California", "us", False, 168, _jobs(6))
        status, entry = db.get_cache_entry("AI Engineer", "indeed", "", "California", "us", False, 168)
        self.assertEqual(status, "fresh")
        self.assertEqual(len(entry["jobs"]), 6)
        self.assertNotIn("_cache_role", entry["jobs"][0])
        self.assertNotIn("_cache_site", entry["jobs"][0])

    def test_missing(self):
        status, entry = db.get_cache_entry("DevOps Engineer", "indeed", "", "Texas", "us", False, 168)
        self.assertEqual(status, "missing")
        self.assertIsNone(entry)

    def test_stale_below_min_volume(self):
        db.save_cache_entry("AI Engineer", "indeed", "", "California", "us", False, 168, _jobs(1))
        status, _ = db.get_cache_entry("AI Engineer", "indeed", "", "California", "us", False, 168,
                                       ttl_hours=12, min_volume=5)
        self.assertEqual(status, "stale")

    def test_stale_when_old(self):
        db.save_cache_entry("AI Engineer", "indeed", "", "California", "us", False, 168, _jobs(6))
        with db._get_conn() as (conn, cur):
            cur.execute("UPDATE job_cache SET scraped_at = '2000-01-01T00:00:00' WHERE role='AI Engineer' AND site='indeed'")
            conn.commit()
        status, _ = db.get_cache_entry("AI Engineer", "indeed", "", "California", "us", False, 168)
        self.assertEqual(status, "stale")

    def test_fallback_state_and_country(self):
        db.save_cache_entry("AI Engineer", "indeed", "", "California", "us", False, 168, _jobs(6))
        status, entry = db.get_cached_jobs("AI Engineer", "indeed", "Palo Alto", "California", "us", False, 168)
        self.assertEqual(status, "fresh")
        self.assertEqual(entry["state"], "California")

        db.save_cache_entry("AI Engineer", "linkedin", "", "", "us", False, 168, _jobs(6))
        status, entry = db.get_cached_jobs("AI Engineer", "linkedin", "Palo Alto", "California", "us", False, 168)
        self.assertEqual(status, "fresh")
        self.assertEqual(entry["country"], "us")

    def test_keep_larger_preserves_entry(self):
        db.save_cache_entry("AI Engineer", "indeed", "", "California", "us", False, 168, _jobs(6), keep_larger=True)
        db.save_cache_entry("AI Engineer", "indeed", "", "California", "us", False, 168, _jobs(2), keep_larger=True)
        _, entry = db.get_cache_entry("AI Engineer", "indeed", "", "California", "us", False, 168)
        self.assertEqual(entry["job_count"], 6)
        db.save_cache_entry("AI Engineer", "indeed", "", "California", "us", False, 168, _jobs(9), keep_larger=True)
        _, entry = db.get_cache_entry("AI Engineer", "indeed", "", "California", "us", False, 168)
        self.assertEqual(entry["job_count"], 9)

    def test_max_jobs_cap(self):
        db.save_cache_entry("AI Engineer", "indeed", "", "California", "us", False, 168, _jobs(300), max_jobs=200)
        _, entry = db.get_cache_entry("AI Engineer", "indeed", "", "California", "us", False, 168)
        self.assertEqual(entry["job_count"], 200)

    def test_strips_session_score_fields(self):
        jobs = _jobs(6)
        jobs[0].update({"keyword_score": 99, "total_score": 99, "ai_score": 99, "reason": "x"})
        db.save_cache_entry("AI Engineer", "indeed", "", "California", "us", False, 168, jobs)
        _, entry = db.get_cache_entry("AI Engineer", "indeed", "", "California", "us", False, 168)
        self.assertNotIn("keyword_score", entry["jobs"][0])
        self.assertNotIn("total_score", entry["jobs"][0])
        self.assertNotIn("ai_score", entry["jobs"][0])
        self.assertNotIn("reason", entry["jobs"][0])

    def test_keeps_url_description_and_job_board(self):
        jobs = _jobs(6)
        jobs[0].update({"job_board": "indeed"})
        db.save_cache_entry("AI Engineer", "indeed", "", "California", "us", False, 168, jobs)
        _, entry = db.get_cache_entry("AI Engineer", "indeed", "", "California", "us", False, 168)
        self.assertEqual(entry["jobs"][0]["url"], "https://acme.example/0")
        self.assertEqual(entry["jobs"][0]["description"], "Building ML systems")
        self.assertEqual(entry["jobs"][0]["job_board"], "indeed")

    def test_gc_by_age(self):
        db.save_cache_entry("AI Engineer", "indeed", "", "California", "us", False, 168, _jobs(6))
        with db._get_conn() as (conn, cur):
            cur.execute("UPDATE job_cache SET scraped_at = '2000-01-01T00:00:00'")
            conn.commit()
        db.gc_job_cache(max_age_hours=336, max_entries=50000)
        status, _ = db.get_cache_entry("AI Engineer", "indeed", "", "California", "us", False, 168)
        self.assertEqual(status, "missing")

    def test_gc_caps_entries(self):
        for i in range(5):
            db.save_cache_entry("AI Engineer", "indeed", "", f"State{i}", "us", False, 168, _jobs(6))
        db.gc_job_cache(max_age_hours=336, max_entries=3)
        with db._get_conn() as (conn, cur):
            cur.execute("SELECT COUNT(*) AS c FROM job_cache")
            count = cur.fetchone()["c"]
        self.assertEqual(count, 3)


# ── prewarm_queue ──

class TestPrewarmQueue(CacheDBTestCase):
    def test_seed_and_priority(self):
        combos = [
            {"role": "AI Engineer", "site": "indeed", "city": "", "state": "Karnataka", "country": "in",
             "internship_mode": False, "hours_old": 168, "source": "config"},
            {"role": "AI Engineer", "site": "indeed", "city": "", "state": "Karnataka", "country": "in",
             "internship_mode": True, "hours_old": 168, "source": "config"},
        ]
        db.seed_prewarm_queue(combos)
        db.seed_prewarm_queue(combos)  # idempotent
        queue = db.get_prewarm_queue()
        self.assertEqual(len(queue), 2)

        db.upsert_prewarm_combo("AI Engineer", "indeed", "", "Karnataka", "in", True)
        db.upsert_prewarm_combo("AI Engineer", "indeed", "", "Karnataka", "in", True)
        queue = db.get_prewarm_queue()
        self.assertEqual(queue[0]["internship_mode"], True)
        self.assertEqual(queue[0]["priority"], 2)

    def test_touch_refreshes_last_refreshed_at(self):
        db.upsert_prewarm_combo("AI Engineer", "indeed", "", "Karnataka", "in", False)
        db.touch_prewarm_combo("AI Engineer", "indeed", "", "Karnataka", "in", False)
        queue = db.get_prewarm_queue()
        self.assertIsNotNone(queue[0]["last_refreshed_at"])


# ── _cache_lookup + run_scrape integration ──

def _make_fake_scraper():
    fake = types.ModuleType("scrapers.fake")

    def scrape_fake(roles=None, location=None, results_wanted=20, internship_mode=False,
                    hours_old=168, fetch_descriptions=None, country_indeed=None):
        role = (roles or ["AI Engineer"])[0]
        return [{"title": f"{role}", "company": "Acme", "url": f"https://acme.example/jobs/{i}",
                 "description": "Building ML systems", "tags": []} for i in range(results_wanted)]

    fake.scrape_fake = scrape_fake
    sys.modules["scrapers.fake"] = fake
    return fake


class TestScrapeCacheIntegration(CacheDBTestCase):
    def setUp(self):
        super().setUp()
        self._fake = _make_fake_scraper()

    def _req(self, **kw):
        from api.schemas import ScrapeRequest
        base = dict(search_id="s1", sites=["fake"], roles=["AI Engineer"], location="California, United States",
                    state="California", country="us", indeed_country="USA", internship_mode=False, hours_old=168,
                    scrape_limit=10)
        base.update(kw)
        return ScrapeRequest(**base)

    def test_run_scrape_writes_cache_and_session(self):
        from api.routes import scrape as scrape_routes

        with patch.object(scrape_routes, "SITE_MAP", {"fake": ("fake", "scrape_fake")}), \
             patch.object(scrape_routes, "_harvest_companies") as harvest:
            scrape_routes.run_scrape(
                "sid-test", ["fake"], ["AI Engineer"], "California, United States", "USA",
                keywords=["ai"], internship_mode=False, scrape_limit=10, hours_old=168,
                city="", state="California", country="us",
            )
            harvest.assert_called_once()
        status, entry = db.get_cache_entry("AI Engineer", "fake", "", "California", "us", False, 168)
        self.assertEqual(status, "fresh")
        self.assertGreaterEqual(len(entry["jobs"]), 10)
        session = db.get_session("sid-test")
        self.assertEqual(session["status"], "done")
        self.assertGreater(session["scraped"], 0)

    def test_cache_hit_returns_no_combos_to_scrape(self):
        from api.routes import scrape as scrape_routes
        from db import save_cache_entry

        save_cache_entry("AI Engineer", "fake", "", "California", "us", False, 168, _jobs(8), keep_larger=True)
        req = self._req()
        with patch.object(scrape_routes, "SITE_MAP", {"fake": ("fake", "scrape_fake")}), \
             patch("db.upsert_prewarm_combo") as upsert:
            combos, initial_jobs, served = scrape_routes._cache_lookup(req)
            self.assertEqual(combos, [])
            self.assertEqual(served, 1)
            self.assertGreaterEqual(len(initial_jobs), 8)
            upsert.assert_not_called()

    def test_cache_miss_schedules_prewarm(self):
        from api.routes import scrape as scrape_routes

        req = self._req()
        with patch.object(scrape_routes, "SITE_MAP", {"fake": ("fake", "scrape_fake")}), \
             patch("db.upsert_prewarm_combo") as upsert:
            combos, initial_jobs, served = scrape_routes._cache_lookup(req)
            self.assertEqual(len(combos), 1)
            self.assertEqual(served, 0)
            self.assertEqual(initial_jobs, [])
            upsert.assert_called_once_with("AI Engineer", "fake", "", "California", "us", False, 168)

    def test_cache_disabled_scrapes_everything(self):
        from api.routes import scrape as scrape_routes

        req = self._req()
        with patch.object(scrape_routes, "SITE_MAP", {"fake": ("fake", "scrape_fake")}), \
             patch("config.CACHE_ENABLED", False), \
             patch("db.upsert_prewarm_combo") as upsert:
            combos, initial_jobs, served = scrape_routes._cache_lookup(req)
            self.assertEqual(len(combos), 1)
            upsert.assert_not_called()

    def test_no_location_fields_scrapes_everything(self):
        from api.routes import scrape as scrape_routes

        req = self._req(country="", state="", city="")
        with patch.object(scrape_routes, "SITE_MAP", {"fake": ("fake", "scrape_fake")}), \
             patch("db.upsert_prewarm_combo") as upsert:
            combos, _, served = scrape_routes._cache_lookup(req)
            self.assertEqual(len(combos), 1)
            self.assertEqual(served, 0)
            upsert.assert_not_called()


if __name__ == "__main__":
    unittest.main()

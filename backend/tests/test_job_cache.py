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


# ── rolling aggregation (country/state → include finer rows) ──

class TestJobCacheAggregate(CacheDBTestCase):
    def test_country_only_unions_states_and_cities(self):
        db.save_cache_entry("Data Scientist", "indeed", "", "", "in", False, 168, _jobs(5))
        db.save_cache_entry("Data Scientist", "indeed", "", "Maharashtra", "in", False, 168, _jobs(4, "mh"))
        db.save_cache_entry("Data Scientist", "indeed", "Mumbai", "Maharashtra", "in", False, 168, _jobs(3, "mm"))
        db.save_cache_entry("Data Scientist", "indeed", "Pune", "Maharashtra", "in", False, 168, _jobs(2, "pn"))
        status, entry = db.get_cached_jobs_aggregate("Data Scientist", "indeed", "", "", "in", False, 168)
        self.assertEqual(status, "fresh")
        self.assertEqual(len(entry["jobs"]), 14)
        self.assertEqual(entry["job_count"], 14)

    def test_aggregate_dedupes_by_url(self):
        dup = _jobs(2, "dup")
        db.save_cache_entry("Data Scientist", "indeed", "", "", "in", False, 168, dup)
        db.save_cache_entry("Data Scientist", "indeed", "", "Maharashtra", "in", False, 168, dup)
        status, entry = db.get_cached_jobs_aggregate("Data Scientist", "indeed", "", "", "in", False, 168, min_volume=1)
        self.assertEqual(status, "fresh")
        self.assertEqual(len(entry["jobs"]), 2)

    def test_aggregate_caps_at_max_jobs(self):
        db.save_cache_entry("Data Scientist", "indeed", "", "", "in", False, 168, _jobs(150))
        db.save_cache_entry("Data Scientist", "indeed", "", "Maharashtra", "in", False, 168, _jobs(150, "mh"))
        status, entry = db.get_cached_jobs_aggregate("Data Scientist", "indeed", "", "", "in", False, 168, max_jobs=200)
        self.assertEqual(status, "fresh")
        self.assertEqual(len(entry["jobs"]), 200)

    def test_aggregate_missing_national_returns_state_rows(self):
        db.save_cache_entry("Data Scientist", "indeed", "", "Maharashtra", "in", False, 168, _jobs(4, "mh"))
        db.save_cache_entry("Data Scientist", "indeed", "", "Karnataka", "in", False, 168, _jobs(3, "ka"))
        status, entry = db.get_cached_jobs_aggregate("Data Scientist", "indeed", "", "", "in", False, 168)
        self.assertEqual(status, "stale")
        self.assertEqual(len(entry["jobs"]), 7)

    def test_aggregate_state_scope_excludes_other_states(self):
        db.save_cache_entry("Data Scientist", "indeed", "", "Maharashtra", "in", False, 168, _jobs(4))
        db.save_cache_entry("Data Scientist", "indeed", "", "Karnataka", "in", False, 168, _jobs(3, "ka"))
        status, entry = db.get_cached_jobs_aggregate("Data Scientist", "indeed", "", "Maharashtra", "in", False, 168, min_volume=1)
        self.assertEqual(status, "fresh")
        self.assertEqual(len(entry["jobs"]), 4)

    def test_aggregate_other_country_excluded(self):
        db.save_cache_entry("Data Scientist", "indeed", "", "", "in", False, 168, _jobs(4))
        db.save_cache_entry("Data Scientist", "indeed", "", "Maharashtra", "us", False, 168, _jobs(3, "us"))
        status, entry = db.get_cached_jobs_aggregate("Data Scientist", "indeed", "", "", "in", False, 168)
        self.assertEqual(len(entry["jobs"]), 4)

    def test_aggregate_city_search_stays_exact(self):
        db.save_cache_entry("Data Scientist", "indeed", "", "", "in", False, 168, _jobs(4))
        db.save_cache_entry("Data Scientist", "indeed", "", "Maharashtra", "in", False, 168, _jobs(3, "mh"))
        db.save_cache_entry("Data Scientist", "indeed", "Mumbai", "Maharashtra", "in", False, 168, _jobs(2, "mm"))
        status, entry = db.get_cached_jobs_aggregate("Data Scientist", "indeed", "Mumbai", "Maharashtra", "in", False, 168, min_volume=1)
        self.assertEqual(status, "fresh")
        self.assertEqual(len(entry["jobs"]), 2)

    def test_aggregate_respects_key_dimensions(self):
        db.save_cache_entry("Data Scientist", "indeed", "", "", "in", False, 168, _jobs(4))
        db.save_cache_entry("Data Scientist", "indeed", "", "", "in", True, 168, _jobs(3, "it"))
        db.save_cache_entry("Data Scientist", "indeed", "", "", "in", False, 48, _jobs(2, "h48"))
        db.save_cache_entry("Data Scientist", "indeed", "", "", "in", False, 168, _jobs(1, "rem"), is_remote=1)
        status, entry = db.get_cached_jobs_aggregate("Data Scientist", "indeed", "", "", "in", False, 168, min_volume=1)
        self.assertEqual(status, "fresh")
        self.assertEqual(len(entry["jobs"]), 4)

    def test_aggregate_broad_fresh_from_child_row(self):
        # No national row at all — a broad search is a cache hit because the
        # Maharashtra child row is fresh and above min_volume (aggregate-based).
        db.save_cache_entry("Data Scientist", "indeed", "", "", "in", False, 168, _jobs(1))
        db.save_cache_entry("Data Scientist", "indeed", "", "Maharashtra", "in", False, 168, _jobs(6, "mh"))
        status, entry = db.get_cached_jobs_aggregate("Data Scientist", "indeed", "", "", "in", False, 168)
        self.assertEqual(status, "fresh")
        self.assertEqual(len(entry["jobs"]), 7)

    def test_aggregate_stale_when_all_rows_below_min_volume(self):
        db.save_cache_entry("Data Scientist", "indeed", "", "", "in", False, 168, _jobs(1))
        db.save_cache_entry("Data Scientist", "indeed", "", "Maharashtra", "in", False, 168, _jobs(4, "mh"))
        status, entry = db.get_cached_jobs_aggregate("Data Scientist", "indeed", "", "", "in", False, 168)
        self.assertEqual(status, "stale")
        self.assertEqual(len(entry["jobs"]), 5)

    def test_aggregate_missing(self):
        status, entry = db.get_cached_jobs_aggregate("DevOps Engineer", "indeed", "", "", "in", False, 168)
        self.assertEqual(status, "missing")
        self.assertIsNone(entry)


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
        locs = (["Mumbai, Maharashtra, India"] * 4
                + ["Pune, Maharashtra, India"] * 3
                + ["Thane, Maharashtra, India"]
                + ["Remote"]
                + ["India"])
        return [{"title": f"{role}", "company": "Acme", "url": f"https://acme.example/jobs/{i}",
                 "description": "Building ML systems", "tags": [],
                 "location": locs[i % len(locs)]} for i in range(results_wanted)]

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
                "sid-test", ["fake"], ["AI Engineer"], "Maharashtra, India", "India",
                keywords=["ai"], internship_mode=False, scrape_limit=10, hours_old=168,
                city="", state="Maharashtra", country="in",
            )
            harvest.assert_called_once()
        # Jobs are keyed by their OWN location, not the searched combo.
        for city, expected in (("Mumbai", 4), ("Pune", 3), ("Thane", 1)):
            status, entry = db.get_cache_entry("AI Engineer", "fake", city, "Maharashtra", "in", False, 168,
                                               min_volume=1)
            self.assertEqual(status, "fresh", f"{city} row should be fresh")
            self.assertEqual(entry["job_count"], expected, f"{city} row count")
        # Remote jobs → is_remote=1 country row; unresolvable → country row.
        status, entry = db.get_cache_entry("AI Engineer", "fake", "", "", "in", False, 168, is_remote=1,
                                           min_volume=1)
        self.assertEqual(entry["job_count"], 1)
        status, entry = db.get_cache_entry("AI Engineer", "fake", "", "", "in", False, 168, is_remote=0,
                                           min_volume=1)
        self.assertEqual(entry["job_count"], 1)
        # Remote and city jobs are aggregated into a country-only search
        # (remote rows are keyed is_remote=1 and excluded from non-remote scopes).
        status, entry = db.get_cached_jobs_aggregate("AI Engineer", "fake", "", "", "in", False, 168)
        self.assertEqual(len(entry["jobs"]), 9)
        session = db.get_session("sid-test")
        self.assertEqual(session["status"], "done")
        self.assertGreater(session["scraped"], 0)

    def test_cache_hit_returns_no_combos_to_scrape(self):
        from api.routes import scrape as scrape_routes
        from db import save_cache_entry

        save_cache_entry("AI Engineer", "fake", "", "California", "us", False, 168, _jobs(12), keep_larger=True)
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

    def test_country_only_serves_state_and_city_rows(self):
        from api.routes import scrape as scrape_routes
        from db import save_cache_entry

        save_cache_entry("AI Engineer", "fake", "", "", "us", False, 168, _jobs(10))
        save_cache_entry("AI Engineer", "fake", "", "California", "us", False, 168, _jobs(4, "ca"))
        save_cache_entry("AI Engineer", "fake", "Palo Alto", "California", "us", False, 168, _jobs(2, "pa"))
        req = self._req(country="us", state="", city="", location="United States")
        with patch.object(scrape_routes, "SITE_MAP", {"fake": ("fake", "scrape_fake")}), \
             patch("db.upsert_prewarm_combo") as upsert:
            combos, initial_jobs, served = scrape_routes._cache_lookup(req)
        self.assertEqual(combos, [])
        self.assertEqual(served, 1)
        self.assertEqual(len(initial_jobs), 16)
        upsert.assert_not_called()

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


# ── _tag_job_location unit tests ──

class TestTagJobLocation(unittest.TestCase):
    def setUp(self):
        from api.routes import scrape as scrape_routes
        self.S = scrape_routes
        self.S._ensure_states()
        self.city_map = {"mumbai": ("Mumbai", "Maharashtra"), "pune": ("Pune", "Maharashtra")}

    def _tag(self, location, country="in"):
        return self.S._tag_job_location({"location": location}, country, self.city_map)

    def test_city_match(self):
        self.assertEqual(self._tag("Mumbai, Maharashtra, India"), ("Mumbai", "Maharashtra", 0))

    def test_city_match_variant_text(self):
        self.assertEqual(self._tag("mumbai, IN"), ("Mumbai", "Maharashtra", 0))

    def test_state_only_match(self):
        self.assertEqual(self._tag("Maharashtra, India"), ("", "Maharashtra", 0))

    def test_unmatched_city_still_matches_state(self):
        self.assertEqual(self._tag("Thane, Maharashtra, India"), ("", "Maharashtra", 0))

    def test_unresolvable_falls_back_to_country(self):
        self.assertEqual(self._tag("India"), ("", "", 0))
        self.assertEqual(self._tag("400001"), ("", "", 0))
        self.assertEqual(self._tag(""), ("", "", 0))

    def test_remote(self):
        self.assertEqual(self._tag("Remote"), ("", "", 1))
        self.assertEqual(self._tag("Anywhere — work from home"), ("", "", 1))
        self.assertEqual(self._tag("Remote (Hybrid), Bengaluru, India"), ("", "", 1))

    def test_state_other_country_not_matched(self):
        self.assertEqual(self._tag("California, United States"), ("", "", 0))

    def test_state_code_MH(self):
        self.assertEqual(self._tag("MH, IN"), ("", "Maharashtra", 0))

    def test_state_code_KA(self):
        self.assertEqual(self._tag("KA, India"), ("", "Karnataka", 0))

    def test_city_beats_state_code(self):
        self.assertEqual(self._tag("Mumbai, MH, India"), ("Mumbai", "Maharashtra", 0))

    def test_state_code_cross_country_rejected(self):
        # 'CA' resolves only under a US search; under an India search it stays unmatched.
        self.assertEqual(self._tag("CA, USA"), ("", "", 0))
        self.assertEqual(self._tag("CA"), ("", "", 0))

    def test_state_code_no_false_positive(self):
        # 'up' must not match inside 'uppal'; no state code equals city-like tokens.
        self.assertEqual(self._tag("Hyderabad, India"), ("", "", 0))
        self.assertEqual(self._tag("Uppal, Telangana, India"), ("", "Telangana", 0))

    def test_blank_job_dict(self):
        self.assertEqual(self.S._tag_job_location({}, "in", self.city_map), ("", "", 0))


if __name__ == "__main__":
    unittest.main()

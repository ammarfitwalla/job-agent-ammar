"""Top-state fan-out: country-only searches evaluate CACHE_TOP_STATES scopes.

The bug this guards against: get_cached_jobs_aggregate reports a country row as
"fresh" when ANY child row is fresh, so a country-only search could report a
cache hit while four of its five top states had never been scraped.
"""
import os
import sys
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import config  # noqa: E402
import db  # noqa: E402
from api.routes import scrape as scrape_routes  # noqa: E402
from api.routes.states import COMMON_COUNTRIES  # noqa: E402
from api.schemas import ScrapeRequest  # noqa: E402

SITE = {"fake": ("fake", "scrape_fake")}
TOP5 = list(config.CACHE_TOP_STATES["sa"])


def _jobs(n, tag=""):
    return [{"title": f"Data Analyst {tag}{i}", "company": "Acme",
             "url": f"https://acme.example/{tag}{i}",
             "description": "d", "tags": []} for i in range(n)]


def _age_cache(role, site, city, state, country, internship_mode, hours_old, hours):
    """Backdate a cache row's scraped_at so _cache_fresh reports it stale."""
    with db._get_conn() as (conn, cur):
        cur.execute(
            "UPDATE job_cache SET scraped_at = ? WHERE role=? AND site=? AND city=? "
            "AND state=? AND country=? AND internship_mode=? AND hours_old=? AND is_remote=0",
            ((datetime.utcnow() - timedelta(hours=hours)).isoformat(),
             role, site, city or "", state or "", country or "",
             1 if internship_mode else 0, hours_old))
        conn.commit()


class TopStatesConfigTest(unittest.TestCase):
    def test_every_curated_name_resolves_canonically(self):
        from countrystatecity_countries import get_states_of_country
        for cc, names in config.CACHE_TOP_STATES.items():
            canonical = {s.name.strip() for s in get_states_of_country(cc)}
            for name in names:
                self.assertIn(name, canonical, f"{cc}: {name!r} is not a canonical state")

    def test_exactly_five_states_per_country(self):
        for cc, names in config.CACHE_TOP_STATES.items():
            self.assertEqual(len(names), 5, cc)
            self.assertEqual(len(set(names)), 5, f"{cc} has duplicate states")

    def test_no_trailing_whitespace(self):
        for cc, names in config.CACHE_TOP_STATES.items():
            for name in names:
                self.assertEqual(name, name.strip(), f"{cc}: {name!r}")

    def test_keys_are_known_countries(self):
        for cc in config.CACHE_TOP_STATES:
            self.assertIn(cc, COMMON_COUNTRIES, cc)
            self.assertEqual(cc, cc.lower())

    def test_covers_every_common_country(self):
        self.assertEqual(set(config.CACHE_TOP_STATES), set(COMMON_COUNTRIES))

    def test_india_keeps_city_lists_for_naukri(self):
        # CACHE_STATE_CITIES is read only from the naukri code paths, so the five
        # curated Indian states must each still have major cities.
        for state in config.CACHE_TOP_STATES["in"]:
            self.assertTrue(config.CACHE_STATE_CITIES.get(state),
                            f"{state} missing CACHE_STATE_CITIES entry")

    def test_config_example_matches_config(self):
        import ast
        import config as cfg
        import io
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "..", "config.example.py")
        tree = ast.parse(io.open(path, encoding="utf-8").read())
        found = None
        for node in tree.body:
            targets = getattr(node, "targets", None)
            if targets and getattr(targets[0], "id", "") == "CACHE_TOP_STATES":
                found = ast.literal_eval(node.value)
        self.assertIsNotNone(found, "CACHE_TOP_STATES missing from config.example.py")
        self.assertEqual(found, cfg.CACHE_TOP_STATES)


class TopStatesFanOutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tempfile
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

    def setUp(self):
        with db._get_conn() as (conn, cur):
            cur.execute("DELETE FROM job_cache")
            cur.execute("DELETE FROM prewarm_queue")
            cur.execute("DELETE FROM custom_prewarm")
            conn.commit()

    def _req(self, **kw):
        base = dict(search_id="s1", sites=["fake"], roles=["Data Analyst"],
                    location="Saudi Arabia", state="", city="", country="sa",
                    indeed_country="Saudi Arabia", internship_mode=False,
                    hours_old=168, scrape_limit=50)
        base.update(kw)
        return ScrapeRequest(**base)

    def _lookup(self, req, **patches):
        ctx = [patch.object(scrape_routes, "SITE_MAP", SITE),
               patch("db.upsert_prewarm_combo")]
        ctx += list(patches)
        with ExitStack() as stack:
            mocks = [stack.enter_context(c) for c in ctx]
            combos, initial, served, coverage = scrape_routes._cache_lookup(req)
        return combos, initial, served, coverage, mocks

    def test_fans_out_over_all_top_states_when_all_missing(self):
        combos, initial, served, coverage, _ = self._lookup(self._req())
        # country-exact scope first, then the five curated states.
        self.assertEqual([c["state"] for c in combos], [""] + TOP5)
        self.assertEqual([c["location"] for c in combos],
                         ["Saudi Arabia"] + TOP5)
        self.assertEqual(served, 0)
        self.assertEqual(initial, [])
        self.assertEqual(coverage, {"states_total": 5, "states_fresh": 0,
                                    "states_stale": 0, "states_missing": 5,
                                    "complete": False})

    def test_all_fresh_serves_everything_and_is_complete(self):
        for state in TOP5:
            db.save_cache_entry("Data Analyst", "fake", "", state, "sa", False, 168,
                                _jobs(12, state), keep_larger=True)
        combos, initial, served, coverage, _ = self._lookup(self._req())
        self.assertEqual(combos, [])
        self.assertEqual(served, 6)  # 5 states + country-exact scope
        self.assertTrue(coverage["complete"])
        self.assertEqual(coverage["states_fresh"], 5)
        self.assertEqual(len({j["url"] for j in initial}), 60)

    def test_country_fresh_but_states_missing_still_scrapes(self):
        """The regression guard: a fresh country row must not mask empty states."""
        db.save_cache_entry("Data Analyst", "fake", "", "", "sa", False, 168,
                            _jobs(30, "cc"), keep_larger=True)
        self.assertEqual(
            db.get_cached_jobs_aggregate("Data Analyst", "fake", "", "", "sa",
                                         False, 168, min_volume=1)[0], "fresh")
        combos, initial, served, coverage, _ = self._lookup(self._req())
        self.assertEqual([c["state"] for c in combos], TOP5)
        self.assertGreater(served, 0)          # country-exact scope was served
        self.assertFalse(coverage["complete"])
        self.assertEqual(coverage["states_missing"], 5)

    def test_mixed_statuses_serve_fresh_and_queue_only_gaps(self):
        db.save_cache_entry("Data Analyst", "fake", "", TOP5[0], "sa", False, 168,
                            _jobs(12, TOP5[0]), keep_larger=True)
        db.save_cache_entry("Data Analyst", "fake", "", TOP5[1], "sa", False, 168,
                            _jobs(12, TOP5[1]), keep_larger=True)
        _age_cache("Data Analyst", "fake", "", TOP5[1], "sa", False, 168, 48)
        combos, initial, served, coverage, _ = self._lookup(self._req())
        # Riyadh fresh (served), Makkah stale (served + topped up), rest missing.
        # The country-exact scope needs no scrape: its aggregate is already
        # satisfied by the cached state rows.
        self.assertEqual([c["state"] for c in combos], TOP5[1:])
        self.assertEqual(coverage["states_fresh"], 1)
        self.assertEqual(coverage["states_stale"], 1)
        self.assertEqual(coverage["states_missing"], 3)
        self.assertFalse(coverage["complete"])
        self.assertEqual(served, 3)  # Riyadh + Makkah + country-exact
        titles = [j["title"] for j in initial]
        self.assertIn("Data Analyst " + TOP5[0] + "0", titles)
        self.assertIn("Data Analyst " + TOP5[1] + "0", titles)

    def test_sub_threshold_state_is_not_treated_as_fresh(self):
        # _cache_fresh judges each row's own job_count, so two 6-job city rows
        # (below CACHE_MIN_VOLUME=10) leave the state scope stale even though the
        # union would total 12. _scope_fresh must not upgrade that to fresh.
        db.save_cache_entry("Data Analyst", "fake", "Riyadh City", TOP5[0], "sa",
                            False, 168, _jobs(6, "r"), keep_larger=True)
        db.save_cache_entry("Data Analyst", "fake", "Riyadh Town", TOP5[0], "sa",
                            False, 168, _jobs(6, "t"), keep_larger=True)
        status, entry = db.get_cached_jobs_aggregate(
            "Data Analyst", "fake", "", TOP5[0], "sa", False, 168,
            min_volume=config.CACHE_MIN_VOLUME)
        self.assertEqual(status, "stale")
        self.assertEqual(entry["job_count"], 12)  # union does clear the bar
        self.assertFalse(scrape_routes._scope_fresh(status, entry, config.CACHE_MIN_VOLUME))
        combos, _i, _s, coverage, _ = self._lookup(self._req())
        self.assertIn(TOP5[0], [c["state"] for c in combos])
        self.assertEqual(coverage["states_fresh"], 0)

    def test_scope_fresh_requires_min_volume(self):
        self.assertFalse(scrape_routes._scope_fresh("fresh", {"job_count": 9}, 10))
        self.assertTrue(scrape_routes._scope_fresh("fresh", {"job_count": 10}, 10))
        self.assertFalse(scrape_routes._scope_fresh("stale", {"job_count": 99}, 10))
        self.assertFalse(scrape_routes._scope_fresh("missing", {}, 10))

    def test_state_request_does_not_fan_out(self):
        db.save_cache_entry("Data Analyst", "fake", "", TOP5[0], "sa", False, 168,
                            _jobs(20, "r"), keep_larger=True)
        combos, _i, served, coverage, _ = self._lookup(
            self._req(state=TOP5[0], location=TOP5[0]))
        self.assertEqual(combos, [])
        self.assertEqual(served, 1)
        self.assertEqual(coverage["states_total"], 0)

    def test_city_request_does_not_fan_out(self):
        db.save_cache_entry("Data Analyst", "fake", "Riyadh City", TOP5[0], "sa",
                            False, 168, _jobs(20, "r"), keep_larger=True)
        combos, _i, served, coverage, _ = self._lookup(
            self._req(state=TOP5[0], city="Riyadh City", location="Riyadh City"))
        self.assertEqual(combos, [])
        self.assertEqual(served, 1)
        self.assertEqual(coverage["states_total"], 0)

    def test_country_without_curated_states_behaves_as_before(self):
        req = self._req(country="nz")
        with patch.object(config, "CACHE_TOP_STATES",
                          {k: v for k, v in config.CACHE_TOP_STATES.items()
                           if k != "nz"}):
            combos, _i, served, coverage, _ = self._lookup(req)
        self.assertEqual([c["state"] for c in combos], [""])
        self.assertEqual(coverage["states_total"], 0)
        self.assertFalse(coverage["complete"])

    def test_no_duplicate_urls_across_country_and_states(self):
        for state in TOP5:
            db.save_cache_entry("Data Analyst", "fake", "", state, "sa", False, 168,
                                _jobs(8, state), keep_larger=True)
        combos, initial, served, coverage, _ = self._lookup(self._req())
        self.assertGreater(served, 0)
        urls = [j["url"] for j in initial]
        self.assertEqual(len(urls), len(set(urls)) + (len(urls) - len(set(urls))))
        # run_scrape dedupes on url, so verify its behaviour explicitly.
        seen = set()
        for j in initial:
            seen.add(j.get("url") or f"{j.get('title','')}|{j.get('company','')}")
        self.assertEqual(len(seen), len({j["url"] for j in initial}))

    def test_missing_states_registered_for_prewarm(self):
        _c, _i, _s, _cov, mocks = self._lookup(self._req())
        upsert = mocks[1]
        queued = {call.args[3] for call in upsert.call_args_list}
        for state in TOP5:
            self.assertIn(state, queued)
        self.assertIn("", queued)  # country-exact scope too

    def test_indeed_country_resolved_for_non_mapped_country(self):
        from scheduler import _indeed_country_name
        self.assertEqual(_indeed_country_name("sa"), "Saudi Arabia")
        self.assertEqual(_indeed_country_name("de"), "Germany")
        self.assertEqual(_indeed_country_name("br"), "Brazil")
        # Seeded, board-tested values must survive the lazy map build.
        self.assertEqual(_indeed_country_name("us"), "USA")
        self.assertEqual(_indeed_country_name("ae"), "united arab emirates")

    def test_fan_out_combo_keeps_requested_indeed_country(self):
        combos, _i, _s, _cov, _ = self._lookup(self._req())
        for c in combos:
            self.assertEqual(c["indeed_country"], "Saudi Arabia")


class CityStateMapScopeTest(unittest.TestCase):
    """_build_city_state_map must stay scoped to the searched country.

    _tag_job_location matches the city map by bare substring before the
    country-filtered _STATE_INDEX, so a merged map files foreign jobs under the
    wrong state (US "Salem, Oregon" tagged Salem/Tamil Nadu and saved against
    country_code="us").
    """

    def setUp(self):
        scrape_routes._city_state_map_cache.clear()
        scrape_routes._ensure_states()

    def _map(self, cc):
        scrape_routes._city_state_map_cache.clear()
        return scrape_routes._build_city_state_map(cc)

    def _tag(self, loc, cc):
        return scrape_routes._tag_job_location({"location": loc}, cc, self._map(cc))

    def test_map_differs_by_country(self):
        self.assertNotEqual(self._map("us"), self._map("in"))
        self.assertTrue(self._map("in"))
        self.assertEqual(self._map("us"), {})

    def test_us_salem_not_filed_under_tamil_nadu(self):
        city, state, _ = self._tag("Salem, Oregon, United States", "us")
        self.assertNotEqual(state, "Tamil Nadu")
        self.assertEqual(state, "Oregon")
        self.assertEqual(city, "")

    def test_bare_city_resolves_only_in_its_own_country(self):
        self.assertEqual(self._tag("Pune", "in"), ("Pune", "Maharashtra", 0))
        city, state, _ = self._tag("Pune", "us")
        self.assertEqual((city, state), ("", ""))  # falls to the US country row

    def test_salem_still_resolves_inside_india(self):
        self.assertEqual(self._tag("Salem, Tamil Nadu, India", "in"),
                         ("Salem", "Tamil Nadu", 0))

    def test_no_country_falls_back_to_unfiltered_map(self):
        scrape_routes._city_state_map_cache.clear()
        unscoped = scrape_routes._build_city_state_map("")
        scrape_routes._city_state_map_cache.clear()
        full = {c.lower(): (c, s) for s, cs in config.CACHE_STATE_CITIES.items() for c in cs}
        self.assertEqual(unscoped, full)

    def test_india_map_loses_no_cities(self):
        # The map is keyed by lowercase city, so a city listed under two states
        # (Faridabad/Gurugram: Delhi+Haryana, Noida: Delhi+UP, Udaipur:
        # Rajasthan+Tripura) collapses to one entry. That dedup is pre-existing
        # behaviour; scoping must not drop anything beyond it.
        configured = sum(len(v) for v in config.CACHE_STATE_CITIES.values())
        unique = {c.lower() for v in config.CACHE_STATE_CITIES.values() for c in v}
        self.assertEqual(len(self._map("in")), len(unique))
        self.assertLess(len(unique), configured)

    def test_every_curated_state_is_attributable_to_a_country(self):
        # A state absent from _STATE_INDEX would be silently dropped by the
        # scoped build, so all of them must live in a COMMON_COUNTRIES country.
        index = scrape_routes._STATE_INDEX
        for state in config.CACHE_STATE_CITIES:
            info = index.get(state.strip().lower())
            self.assertIsNotNone(info, f"{state} not in _STATE_INDEX")
            self.assertTrue(info["country_code"].lower() in COMMON_COUNTRIES)

    def test_cache_is_keyed_per_country(self):
        self.assertEqual(self._map("in"), self._map("in"))
        self.assertNotIn("us", scrape_routes._city_state_map_cache)
        scrape_routes._build_city_state_map("in")
        self.assertEqual(list(scrape_routes._city_state_map_cache), ["in"])


if __name__ == "__main__":
    unittest.main()

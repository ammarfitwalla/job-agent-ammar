import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import db  # noqa: E402
from api.routes.admin import (  # noqa: E402
    _attach_user_geo, _format_user_geo, _user_geo_maps,
)


def _add_visit(visit_id, country="", city="", region="", email="", ip="", when=None):
    with db._write_lock:
        with db._get_conn() as (conn, cur):
            cur.execute(
                """INSERT INTO visits (visit_id, ip_address, device_type, path,
                                      user_email, country, city, region, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (visit_id, ip, "desktop", "/", email, country, city, region,
                 when or db._now()),
            )
            conn.commit()


class FormatUserGeoTestCase(unittest.TestCase):
    def test_full_stack(self):
        self.assertEqual(
            _format_user_geo({"country": "India", "city": "Jamshedpur", "region": "Jharkhand"}),
            "Jamshedpur, Jharkhand, India")

    def test_city_equal_to_region_is_not_repeated(self):
        self.assertEqual(
            _format_user_geo({"country": "Germany", "city": "Berlin", "region": "Berlin"}),
            "Berlin, Germany")

    def test_region_containing_country_does_not_duplicate(self):
        # ip-api returns regionName like "Savona, Italy" for some regions.
        self.assertEqual(
            _format_user_geo({"country": "Italy", "city": "Testico", "region": "Savona, Italy"}),
            "Testico, Savona, Italy")

    def test_country_only(self):
        self.assertEqual(_format_user_geo({"country": "India", "city": "", "region": ""}), "India")

    def test_empty_and_none(self):
        self.assertEqual(_format_user_geo({"country": "", "city": "", "region": ""}), "")
        self.assertEqual(_format_user_geo(None), "")
        self.assertEqual(_format_user_geo({}), "")

    def test_missing_keys_tolerated(self):
        self.assertEqual(_format_user_geo({"city": "Pune"}), "Pune")


class UserGeoMapsTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fd, cls.tmp = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        db._DB_PATH = cls.tmp
        db.init_db()
        _add_visit("v1", country="India", city="Pune", region="Maharashtra",
                   email="a@x.com", ip="9.9.9.9")
        # A later visit for the same user wins.
        _add_visit("v2", country="India", city="Mumbai", region="Maharashtra",
                   email="a@x.com", ip="9.9.9.9")
        _add_visit("v3", country="Germany", city="Berlin", region="Berlin",
                   email="b@x.com", ip="8.8.8.8")
        # No country -> must not appear in the maps at all.
        _add_visit("v4", country="", email="c@x.com", ip="7.7.7.7")

    @classmethod
    def tearDownClass(cls):
        try:
            os.remove(cls.tmp)
        except OSError:
            pass
        db._DB_PATH = os.path.join(os.path.dirname(os.path.abspath(db.__file__)), "job_agent.db")

    def test_latest_visit_wins_per_email(self):
        by_email, _ = _user_geo_maps()
        self.assertEqual(by_email["a@x.com"]["city"], "Mumbai")
        self.assertEqual(by_email["b@x.com"]["country"], "Germany")

    def test_uncountryed_visit_excluded(self):
        by_email, by_ip = _user_geo_maps()
        self.assertNotIn("c@x.com", by_email)
        self.assertNotIn("7.7.7.7", by_ip)

    def test_ip_map_populated(self):
        _, by_ip = _user_geo_maps()
        self.assertEqual(by_ip["8.8.8.8"]["city"], "Berlin")


class AttachUserGeoTestCase(unittest.TestCase):
    def _attach(self, sessions):
        by_email = {"a@x.com": {"country": "India", "city": "Pune", "region": "Maharashtra"}}
        by_ip = {"8.8.8.8": {"country": "Germany", "city": "Berlin", "region": "Berlin"}}
        _attach_user_geo(sessions, by_email, by_ip)
        return sessions

    def test_session_own_geo_wins(self):
        s = self._attach([{
            "user_country": "India", "user_city": "Delhi", "user_region": "Delhi",
            "user_email": "a@x.com", "ip_address": "8.8.8.8",
        }])[0]
        self.assertEqual(s["user_location"], "Delhi, India")
        self.assertEqual(s["user_location_source"], "session")

    def test_falls_back_to_visit_by_email(self):
        s = self._attach([{
            "user_country": "", "user_city": "", "user_region": "",
            "user_email": "a@x.com", "ip_address": "",
        }])[0]
        self.assertEqual(s["user_location"], "Pune, Maharashtra, India")
        self.assertEqual(s["user_location_source"], "visit")

    def test_falls_back_to_visit_by_ip(self):
        s = self._attach([{
            "user_country": "", "user_city": "", "user_region": "",
            "user_email": "", "ip_address": "8.8.8.8",
        }])[0]
        self.assertEqual(s["user_location"], "Berlin, Germany")
        self.assertEqual(s["user_location_source"], "ip")

    def test_unattributable_yields_empty_not_a_guess(self):
        s = self._attach([{
            "user_country": "", "user_city": "", "user_region": "",
            "user_email": "", "ip_address": "",
        }])[0]
        self.assertEqual(s["user_location"], "")
        self.assertEqual(s["user_location_source"], "")

    def test_keys_always_present(self):
        s = self._attach([{"user_email": "z@x.com"}])[0]
        self.assertIn("user_location", s)
        self.assertIn("user_location_source", s)


if __name__ == "__main__":
    unittest.main(verbosity=2)

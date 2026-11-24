"""Title matching must recognize spelling variants of the same role.

The scrape pipeline drops jobs whose title doesn't match the searched role. A
role like "MLOps Engineer" was rejecting "ML Ops Engineer" and "Machine
Learning Operations Engineer" because the glued acronym wasn't expanded.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from match_engine.relevance_engine import role_match_count  # noqa: E402

ROLE = "MLOps Engineer"


class MLOpsVariantsTestCase(unittest.TestCase):
    def test_variants_match(self):
        titles = [
            "MLOps Engineer",
            "Senior MLOps Engineer",
            "ML Ops Engineer",
            "ML-Ops Engineer",
            "ML Operations Engineer",
            "Machine Learning Operations Engineer",
            "Machine Learning Ops Engineer",
            "AI/ML Ops Engineer",
        ]
        for title in titles:
            with self.subTest(title=title):
                self.assertEqual(role_match_count(title, [ROLE]), 1)

    def test_unrelated_titles_do_not_match(self):
        for title in ("Accountant", "Sales Manager", "Registered Nurse"):
            with self.subTest(title=title):
                self.assertEqual(role_match_count(title, [ROLE]), 0)

    def test_plural_roles_still_work(self):
        self.assertEqual(role_match_count("Senior Data Engineer", ["Data Engineer"]), 1)
        # A broader "ML Engineer" search should include an MLOps title.
        self.assertEqual(role_match_count("MLOps Engineer", ["ML Engineer"]), 1)


if __name__ == "__main__":
    unittest.main()

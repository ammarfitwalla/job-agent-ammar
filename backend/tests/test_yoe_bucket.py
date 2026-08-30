import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from utils.experience_level import (  # noqa: E402
    YOE_NOT_SPECIFIED,
    yoe_bucket_from_job,
)


class YoeBucketTestCase(unittest.TestCase):
    def _b(self, desc, title="", job_level=""):
        return yoe_bucket_from_job(title, desc, job_level)

    def test_ranges_use_minimum(self):
        self.assertEqual(self._b("5-7 years experience"), "4-7")
        self.assertEqual(self._b("3-5 years of experience"), "2-4")
        self.assertEqual(self._b("2-4 years"), "2-4")
        self.assertEqual(self._b("1-2 years experience"), "0-2")
        self.assertEqual(self._b("0-2 years experience"), "0-2")
        self.assertEqual(self._b("4-6 yrs"), "4-7")
        self.assertEqual(self._b("7-10 years"), "7-10")
        self.assertEqual(self._b("8-10 years"), "7-10")
        self.assertEqual(self._b("10-12 years"), "7-10")

    def test_plus_and_at_least(self):
        self.assertEqual(self._b("5+ years experience"), "4-7")
        self.assertEqual(self._b("5+ years of experience"), "4-7")
        self.assertEqual(self._b("at least 8 years"), "7-10")
        self.assertEqual(self._b("minimum of 3 years"), "2-4")
        self.assertEqual(self._b("min 10 years"), "7-10")
        self.assertEqual(self._b("We require 11+ years"), "10+")

    def test_bare_n_years_with_context(self):
        self.assertEqual(self._b("We require 10 years of experience"), "7-10")
        self.assertEqual(self._b("requires 2 years experience"), "2-4")
        self.assertEqual(self._b("5 years of relevant experience in AI"), "4-7")

    def test_boundaries(self):
        self.assertEqual(self._b("3 years experience"), "2-4")
        self.assertEqual(self._b("4 years experience"), "4-7")
        self.assertEqual(self._b("5 years experience"), "4-7")
        self.assertEqual(self._b("6 years experience"), "4-7")
        self.assertEqual(self._b("7 years experience"), "7-10")
        self.assertEqual(self._b("8 years experience"), "7-10")
        self.assertEqual(self._b("10 years experience"), "7-10")
        self.assertEqual(self._b("11 years experience"), "10+")
        self.assertEqual(self._b("12 years experience"), "10+")

    def test_false_positives_ignored(self):
        self.assertEqual(self._b("Salary: $70k - $90k per annum"), YOE_NOT_SPECIFIED)
        self.assertEqual(self._b("$100,000 base, no experience needed"), YOE_NOT_SPECIFIED)
        self.assertEqual(self._b("The candidate is 5 years old or a 3 years ago grad"), YOE_NOT_SPECIFIED)
        self.assertEqual(self._b("2 years ago we founded the company"), YOE_NOT_SPECIFIED)
        self.assertEqual(self._b("Contract willing to work for 2 years"), YOE_NOT_SPECIFIED)

    def test_salary_does_not_stop_real_yoe(self):
        self.assertEqual(self._b("$80k - $100k, 5+ years experience"), "4-7")

    def test_seniority_fallback_title(self):
        self.assertEqual(yoe_bucket_from_job("Senior Data Engineer", "", ""), "4-7")
        self.assertEqual(yoe_bucket_from_job("Senior Manager, Analytics", "", ""), "7-10")
        self.assertEqual(yoe_bucket_from_job("Principal Engineer", "", ""), "7-10")
        self.assertEqual(yoe_bucket_from_job("VP Engineering", "", ""), "10+")
        self.assertEqual(yoe_bucket_from_job("Director of Data", "", ""), "10+")
        self.assertEqual(yoe_bucket_from_job("Software Development Intern", "", ""), "0-2")
        self.assertEqual(yoe_bucket_from_job("Junior QA Engineer", "", ""), "0-2")
        self.assertEqual(yoe_bucket_from_job("Mid-level Backend Dev", "", ""), "2-4")

    def test_job_level_fallback(self):
        self.assertEqual(self._b("", job_level="director"), "10+")
        self.assertEqual(self._b("", job_level="entry level"), "0-2")
        self.assertEqual(self._b("", job_level="mid-senior level"), "4-7")
        self.assertEqual(self._b("", job_level="Senior"), "4-7")

    def test_description_fallback(self):
        self.assertEqual(self._b("You are a senior developer on our team"), "4-7")
        self.assertEqual(self._b("Looking for a tech lead to own the platform"), "7-10")

    def test_empty_returns_not_specified(self):
        self.assertEqual(self._b(""), YOE_NOT_SPECIFIED)
        self.assertEqual(self._b(None), YOE_NOT_SPECIFIED)


if __name__ == "__main__":
    unittest.main()
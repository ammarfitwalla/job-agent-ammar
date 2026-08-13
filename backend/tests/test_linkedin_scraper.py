import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scrapers.linkedin_scraper import _scrape_http, LINKEDIN_BATCH_SIZE


class TestLinkedinScraperLogic(unittest.TestCase):
    def setUp(self):
        self.delay_patcher = patch("scrapers.linkedin_scraper.delay", lambda *args, **kwargs: None)
        self.enrich_patcher = patch("scrapers.linkedin_scraper.enrich_descriptions")
        self.delay_patcher.start()
        self.mock_enrich = self.enrich_patcher.start()

    def tearDown(self):
        self.delay_patcher.stop()
        self.enrich_patcher.stop()

    def test_scrape_http_filters_by_location_and_duplicates(self):
        raw_jobs = [
            {
                "title": "Software Engineer",
                "company": "Acme",
                "company_url": "https://acme.example.com",
                "location": "New York, NY",
                "url": "https://www.linkedin.com/jobs/view/123",
                "posted_at": "2026-08-12",
                "salary": "$120k",
                "job_id": "123",
            },
            {
                "title": "Software Engineer",
                "company": "Acme",
                "company_url": "https://acme.example.com",
                "location": "New York, NY",
                "url": "https://www.linkedin.com/jobs/view/123",
                "posted_at": "2026-08-12",
                "salary": "$120k",
                "job_id": "123",
            },
            {
                "title": "Data Scientist",
                "company": "Acme",
                "company_url": "https://acme.example.com",
                "location": "San Francisco, CA",
                "url": "https://www.linkedin.com/jobs/view/456",
                "posted_at": "2026-08-12",
                "salary": "$130k",
                "job_id": "456",
            },
            {
                "title": "General interest application",
                "company": "Acme",
                "company_url": "https://acme.example.com",
                "location": "New York, NY",
                "url": "https://www.linkedin.com/jobs/view/789",
                "posted_at": "2026-08-12",
                "salary": "$110k",
                "job_id": "789",
            },
        ]

        with patch("scrapers.linkedin_scraper._fetch_linkedin_batch", return_value=(raw_jobs, LINKEDIN_BATCH_SIZE)) as mock_batch:
            jobs = _scrape_http([
                "Software Engineer"
            ], "New York, NY", internship_mode=False, results_wanted=10, hours_old=72, fetch_descriptions=False)

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["url"], "https://www.linkedin.com/jobs/view/123")
        self.assertEqual(jobs[0]["location"], "New York, NY")
        mock_batch.assert_called_once()

    def test_scrape_http_respects_results_wanted(self):
        raw_jobs = []
        for idx in range(1, 6):
            raw_jobs.append({
                "title": f"Software Engineer {idx}",
                "company": "Acme",
                "company_url": "https://acme.example.com",
                "location": "New York, NY",
                "url": f"https://www.linkedin.com/jobs/view/{100 + idx}",
                "posted_at": "2026-08-12",
                "salary": "$120k",
                "job_id": str(100 + idx),
            })

        # Return enough jobs in one batch to force the per-role limit.
        with patch("scrapers.linkedin_scraper._fetch_linkedin_batch", return_value=(raw_jobs, LINKEDIN_BATCH_SIZE)):
            jobs = _scrape_http([
                "Software Engineer"
            ], "United States", internship_mode=False, results_wanted=3, hours_old=72, fetch_descriptions=False)

        self.assertEqual(len(jobs), 3)
        self.assertEqual(jobs[0]["title"], "Software Engineer 1")
        self.assertEqual(jobs[-1]["title"], "Software Engineer 3")

    def test_scrape_http_internship_mode_uses_intern_fallback(self):
        fallback_jobs = [
            {
                "title": "Software Engineering Intern",
                "company": "Acme",
                "company_url": "https://acme.example.com",
                "location": "New York, NY",
                "url": "https://www.linkedin.com/jobs/view/999",
                "posted_at": "2026-08-12",
                "salary": "$40k",
                "job_id": "999",
            }
        ]

        batch_side_effect = [([], 0), ([], 0), (fallback_jobs, LINKEDIN_BATCH_SIZE)]
        with patch("scrapers.linkedin_scraper._fetch_linkedin_batch", side_effect=batch_side_effect) as mock_batch:
            jobs = _scrape_http([
                "Software Engineer"
            ], "New York, NY", internship_mode=True, results_wanted=1, hours_old=72, fetch_descriptions=False)

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["url"], "https://www.linkedin.com/jobs/view/999")
        self.assertEqual(jobs[0]["title"], "Software Engineering Intern")
        self.assertEqual(mock_batch.call_count, 3)

    def test_scrape_http_returns_empty_for_no_roles(self):
        jobs = _scrape_http([], "United States", internship_mode=False, results_wanted=5, hours_old=72, fetch_descriptions=False)
        self.assertEqual(jobs, [])


if __name__ == "__main__":
    unittest.main()

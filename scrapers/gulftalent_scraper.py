# scrapers/gulftalent_scraper.py
import requests
from utils.logger import log
from config import SCRAPE_LIMIT, TARGET_ROLES


def scrape_gulftalent():
    log("[SCRAPER] GulfTalent started")

    query = ",".join(TARGET_ROLES)
    url = f"https://www.gulftalent.com/mobile-api/jobs?keywords={query}"

    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        data = r.json().get("jobs", [])
        jobs = []

        for job in data[:SCRAPE_LIMIT]:
            jobs.append({
                "title": job.get("title", ""),
                "company": job.get("company_name", ""),
                "location": f"{job.get('city','')} {job.get('country','')}",
                "url": "https://www.gulftalent.com" + job.get("view_url", ""),
                "description": job.get("job_description", "")[:2000]
            })

        log(f"[SCRAPER] GulfTalent found: {len(jobs)} jobs")
        return jobs

    except Exception as e:
        log(f"[GULF ERROR] {e}")
        return []

# remoteok scraper (fixed using RemoteOK API)
import requests
from bs4 import BeautifulSoup
from utils.logger import log
from config import SCRAPE_LIMIT, TARGET_ROLES


def scrape_remoteok():
    log("[SCRAPER] RemoteOK started")
    jobs = []

    try:
        # RemoteOK Public API
        r = requests.get(
            "https://remoteok.com/api",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10
        )

        data = r.json()

        # API includes metadata in first element
        postings = [job for job in data if isinstance(job, dict)]

        for job in postings:
            # Filter by your keywords
            role_text = f"{job.get('position','')} {job.get('tags',[])}".lower()
            if not any(keyword.lower() in role_text for keyword in TARGET_ROLES):
                continue

            title = job.get("position", "").strip()
            company = job.get("company", "").strip()
            url = job.get("url", "").strip()
            location = "Remote"

            # Description is HTML → strip tags
            desc_html = job.get("description", "")
            soup = BeautifulSoup(desc_html, "html.parser")
            description = soup.get_text().strip()

            jobs.append({
                "title": title,
                "company": company,
                "location": location,
                "url": url,
                "description": description
            })

            if len(jobs) >= SCRAPE_LIMIT:
                break

        log(f"[SCRAPER] RemoteOK found: {len(jobs)} jobs")
        return jobs

    except Exception as e:
        log(f"[RemoteOK ERROR] {e}")
        return []

# scrapers/eurojobs_scraper.py
from bs4 import BeautifulSoup
from utils.logger import log
from config import SCRAPE_LIMIT, TARGET_ROLES
from browser import fetch_html


def scrape_eurojobs():
    log("[SCRAPER] EuroJobs started")
    jobs = []

    query = "+".join(TARGET_ROLES)
    url = f"https://www.eurojobs.com/search/?keywords={query}"

    try:
        html = fetch_html(url, wait=5)
        soup = BeautifulSoup(html, "html.parser")

        listings = soup.select("div.job-item")

        for job in listings[:SCRAPE_LIMIT]:
            title = job.select_one("a.title")
            company = job.select_one(".company")
            location = job.select_one(".city-country")

            if not title:
                continue

            job_url = "https://www.eurojobs.com" + title["href"]

            jd_html = fetch_html(job_url, wait=3)
            jd_soup = BeautifulSoup(jd_html, "html.parser")

            desc = jd_soup.get_text().strip()

            jobs.append({
                "title": title.text.strip(),
                "company": company.text.strip() if company else "Unknown",
                "location": location.text.strip() if location else "",
                "url": job_url,
                "description": desc
            })

        log(f"[SCRAPER] EuroJobs found: {len(jobs)} jobs")
        return jobs

    except Exception as e:
        log(f"[EUROJOBS ERROR] {e}")
        return []

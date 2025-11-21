# scrapers/naukri_scraper.py
from bs4 import BeautifulSoup
from browser import fetch_html
from utils.logger import log
from config import SCRAPE_LIMIT, TARGET_ROLES


def scrape_naukri():
    log("[SCRAPER] Naukri started")
    jobs = []

    query = "-".join(TARGET_ROLES)
    url = f"https://www.naukri.com/{query}-jobs"

    try:
        html = fetch_html(url, wait=5)
        soup = BeautifulSoup(html, "html.parser")

        listings = soup.select("article.jobTuple")

        for job in listings[:SCRAPE_LIMIT]:
            title = job.select_one(".title")
            company = job.select_one(".subTitle")
            location = job.select_one(".location")

            link = job.select_one("a.title")
            if not link:
                continue

            job_url = link["href"]

            jd_html = fetch_html(job_url, wait=3)
            jd_soup = BeautifulSoup(jd_html, "html.parser")

            desc_block = jd_soup.select_one(".dang-inner-html")
            desc = desc_block.get_text(" ").strip() if desc_block else ""

            jobs.append({
                "title": title.text.strip() if title else "",
                "company": company.text.strip() if company else "",
                "location": location.text.strip() if location else "",
                "url": job_url,
                "description": desc
            })

        log(f"[SCRAPER] Naukri found: {len(jobs)} jobs")
        return jobs

    except Exception as e:
        log(f"[NAUKRI ERROR] {e}")
        return []

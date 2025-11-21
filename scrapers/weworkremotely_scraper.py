# scrapers/weworkremotely_scraper.py

from bs4 import BeautifulSoup
from utils.logger import log
from config import SCRAPE_LIMIT
from browser import fetch_html

def scrape_wwr():
    log("[SCRAPER] WeWorkRemotely started")
    jobs = []

    url = "https://weworkremotely.com/categories/remote-programming-jobs"

    try:
        html = fetch_html(url, wait=5)
        soup = BeautifulSoup(html, "html.parser")

        # The correct updated selector
        listings = soup.select("li.new-listing-container.feature")

        for item in listings[:SCRAPE_LIMIT]:

            # Correct job link
            link = item.select_one("a.listing-link--unlocked")
            if not link:
                continue

            job_url = "https://weworkremotely.com" + link["href"]

            # Extract title, company, region
            title = item.select_one("span.title")
            company = item.select_one("span.company")
            region = item.select_one("span.region")

            # Fetch job page description
            jd_html = fetch_html(job_url, wait=3)
            jd_soup = BeautifulSoup(jd_html, "html.parser")

            desc_block = jd_soup.select_one("div.listing-container")
            desc = desc_block.get_text(" ").strip() if desc_block else ""

            jobs.append({
                "title": title.text.strip() if title else "",
                "company": company.text.strip() if company else "",
                "location": region.text.strip() if region else "Remote",
                "url": job_url,
                "description": desc
            })

        log(f"[SCRAPER] WWR found: {len(jobs)} jobs")
        return jobs

    except Exception as e:
        log(f"[WWR ERROR] {e}")
        return []

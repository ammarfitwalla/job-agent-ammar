# scrapers/weworkremotely_scraper.py

from bs4 import BeautifulSoup
from utils.logger import log
from config import SCRAPE_LIMIT
from browser import fetch_html

BASE_URL = "https://weworkremotely.com"


def scrape_wwr():
    log("[SCRAPER] WeWorkRemotely started")
    jobs = []

    url = f"{BASE_URL}/categories/remote-full-stack-programming-jobs#job-listings"
    # you can change the category URL if you want, but selector logic stays same

    try:
        html = fetch_html(url, wait=5)
        soup = BeautifulSoup(html, "html.parser")

        # Matches those <li class="new-listing-container feature"> ... </li>
        listings = soup.select("li.new-listing-container.feature")

        for item in listings[:SCRAPE_LIMIT]:
            # Correct job link
            link = item.select_one("a.listing-link--unlocked")
            if not link or not link.get("href"):
                continue

            job_url = BASE_URL + link["href"]

            # ✅ Updated selectors
            title_el = item.select_one("h3.new-listing__header__title")
            company_el = item.select_one("p.new-listing__company-name")
            region_el = item.select_one("p.new-listing__company-headquarters")

            title = title_el.get_text(strip=True) if title_el else ""
            company = company_el.get_text(strip=True) if company_el else ""
            location = region_el.get_text(strip=True) if region_el else "Remote"

            # Fetch job page description
            jd_html = fetch_html(job_url, wait=3)
            jd_soup = BeautifulSoup(jd_html, "html.parser")

            # ✅ Updated description selector
            desc_block = jd_soup.select_one("div.lis-container__job__content__description")
            desc = desc_block.get_text(" ", strip=True) if desc_block else ""

            print({
                "title": title,
                "company": company,
                "location": location,
                "url": job_url,
                "description": desc
            })

            jobs.append({
                "title": title,
                "company": company,
                "location": location,
                "url": job_url,
                "description": desc
            })

        log(f"[SCRAPER] WWR found: {len(jobs)} jobs")
        return jobs

    except Exception as e:
        log(f"[WWR ERROR] {e}")
        return []

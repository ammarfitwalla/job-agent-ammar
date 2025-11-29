# scrapers/naukri_scraper.py
from bs4 import BeautifulSoup
from browser import fetch_html
from utils.logger import log
from config import SCRAPE_LIMIT, TARGET_ROLES
import urllib.parse

def scrape_naukri():
    log("[SCRAPER] Naukri started")
    jobs = []

    # Construct search URL
    query = "-".join(TARGET_ROLES)
    url = f"https://www.naukri.com/{query}-jobs"

    try:
        # Fetch HTML with longer wait time for dynamic content
        html = fetch_html(url, wait=10)
        soup = BeautifulSoup(html, "html.parser")

        # Debug: Dump HTML to file
        # with open("naukri_debug_dump.html", "w", encoding="utf-8") as f:
        #     f.write(soup.prettify())

        # Selectors based on investigation
        # Try multiple potential container selectors
        listings = soup.select("article.jobTuple")
        if not listings:
            listings = soup.select("div.jobTuple")
        
        # Fallback: Try generic row selector if specific tuple fails
        if not listings:
            listings = soup.select("div.srp-jobtuple-wrapper")

        log(f"[NAUKRI DEBUG] Found {len(listings)} listings")

        for job in listings[:SCRAPE_LIMIT]:
            try:
                # Title
                title_elem = job.select_one("a.title")
                if not title_elem:
                    continue
                title = title_elem.text.strip()
                
                # Link
                job_url = title_elem["href"]
                
                # Company
                company_elem = job.select_one("a.comp-name")
                company = company_elem.text.strip() if company_elem else "Unknown Company"
                
                # Location - try multiple selectors
                location = "Unknown Location"
                loc_elem = job.select_one(".locWdth")
                if not loc_elem:
                    loc_elem = job.select_one(".location")
                if not loc_elem:
                    # Try finding li with location icon or class
                    loc_elem = job.select_one("li.location")
                
                if loc_elem:
                    location = loc_elem.text.strip()

                # Description - simplified
                desc = f"Job for {title} at {company} in {location}. See link for details."

                jobs.append({
                    "title": title,
                    "company": company,
                    "location": location,
                    "url": job_url,
                    "description": desc
                })
            except Exception as e:
                log(f"[NAUKRI ERROR] Error parsing job item: {e}")
                continue

        log(f"[SCRAPER] Naukri found: {len(jobs)} jobs")
        return jobs

    except Exception as e:
        log(f"[NAUKRI ERROR] {e}")
        return []

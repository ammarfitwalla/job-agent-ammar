# scrapers/gulftalent_scraper.py
from bs4 import BeautifulSoup
from utils.logger import log
from config import SCRAPE_LIMIT, TARGET_ROLES
from browser import fetch_html
import urllib.parse

def scrape_gulftalent():
    log("[SCRAPER] GulfTalent started")
    jobs = []

    # Construct search URL
    # GulfTalent uses 'pos_ref' for keywords
    query = " ".join(TARGET_ROLES)
    encoded_query = urllib.parse.quote(query)
    url = f"https://www.gulftalent.com/jobs/search?pos_ref={encoded_query}"

    try:
        # Use fetch_html which now uses undetected-chromedriver
        html = fetch_html(url, wait=5)
        soup = BeautifulSoup(html, "html.parser")

        # Selectors based on investigation
        listings = soup.select("a.ga-job-impression.ga-job-click")

        for item in listings[:SCRAPE_LIMIT]:
            try:
                # Title is in strong tag
                title_elem = item.select_one("strong")
                title = title_elem.text.strip() if title_elem else "Unknown Title"

                # Company is in a.text-muted
                # Note: The company link might be inside the container or adjacent
                # Based on investigation: "Company name: a.text-muted (within the container)"
                company_elem = item.select_one("a.text-muted")
                company = company_elem.text.strip() if company_elem else "Unknown Company"

                # Location is in a.text-regular span
                location_elem = item.select_one("a.text-regular span")
                location = location_elem.text.strip() if location_elem else "Unknown Location"

                # Link is the href of the container itself
                job_url = item.get("href")
                if job_url and not job_url.startswith("http"):
                    job_url = "https://www.gulftalent.com" + job_url

                # Description - we could fetch individual pages, but let's keep it simple for now
                # and just use the title/company as description or fetch if needed.
                # For now, let's leave description empty or generic to save time/resources
                # unless we want to fetch every single page.
                # Let's fetch the page to get a proper description if possible, or just use a placeholder.
                # Fetching every page might be slow. Let's try to get a snippet if available.
                # The investigation said description is not visible.
                # Let's just use the title and location as a placeholder description for now to avoid 
                # making 20+ extra requests which might trigger rate limits.
                desc = f"Job for {title} at {company} in {location}. See link for details."

                jobs.append({
                    "title": title,
                    "company": company,
                    "location": location,
                    "url": job_url,
                    "description": desc
                })
            except Exception as e:
                log(f"[GULF ERROR] Error parsing job item: {e}")
                continue

        log(f"[SCRAPER] GulfTalent found: {len(jobs)} jobs")
        return jobs

    except Exception as e:
        log(f"[GULF ERROR] {e}")
        return []

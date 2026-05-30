# scrapers/eurojobs_scraper.py
from bs4 import BeautifulSoup
from utils.logger import log
from config import SCRAPE_LIMIT, TARGET_ROLES
from browser import fetch_html
import urllib.parse

def scrape_eurojobs():
    log("[SCRAPER] EuroJobs started")
    jobs = []

    # Construct search URL
    # Using the correct format provided by user
    query = "+".join(TARGET_ROLES)
    encoded_query = urllib.parse.quote(query)
    # The URL format is specific:
    # https://eurojobs.com/search-results-jobs/?action=search&listing_type[equal]=Job&keywords[all_words]=Data+Scientist...
    url = f"https://eurojobs.com/search-results-jobs/?action=search&listing_type[equal]=Job&keywords[all_words]={encoded_query}&Location[location][value]=&Location[location][radius]=10"

    try:
        html = fetch_html(url, wait=5)
        soup = BeautifulSoup(html, "html.parser")

        # Debug: Dump HTML to file
        # with open("eurojobs_debug_dump.html", "w", encoding="utf-8") as f:
        #     f.write(soup.prettify())
            
        # Selectors based on investigation of search results page
        # Job container: div.job-listing.job-listing--regular
        listings = soup.select("div.job-listing.job-listing--regular")
        
        # Fallback: Try to find any job links if main selector fails
        if not listings:
            log("[EUROJOBS DEBUG] Main selector failed, trying fallback a[href*='/job/']")
            # Look for links that look like job postings
            potential_links = soup.select("a[href*='/job/']")
            log(f"[EUROJOBS DEBUG] Found {len(potential_links)} potential job links")
            
            # If we found links, try to construct job objects from them
            # This is a desperate fallback
            for link in potential_links[:SCRAPE_LIMIT]:
                try:
                    title = link.text.strip()
                    if not title: continue
                    
                    job_url = link["href"]
                    if not job_url.startswith("http"):
                        job_url = "https://eurojobs.com" + job_url
                        
                    jobs.append({
                        "title": title,
                        "company": "Unknown (Fallback)",
                        "location": "Europe",
                        "url": job_url,
                        "description": f"Job: {title}"
                    })
                except: continue
            
            if jobs:
                log(f"[SCRAPER] EuroJobs found: {len(jobs)} jobs (via fallback)")
                return jobs

        # Debug logging
        log(f"[EUROJOBS DEBUG] Found {len(listings)} listings with selector 'div.job-listing.job-listing--regular'")

        for item in listings[:SCRAPE_LIMIT]:
            try:
                # Title is in a.job-listing__title
                title_elem = item.select_one("a.job-listing__title")
                if not title_elem:
                    continue
                
                title = title_elem.text.strip()
                job_url = title_elem["href"]
                if job_url and not job_url.startswith("http"):
                    job_url = "https://eurojobs.com" + job_url

                # Company is in div.job-listing__company
                company_elem = item.select_one("div.job-listing__company")
                company = company_elem.text.strip() if company_elem else "Unknown Company"

                # Location is in div.job-listing__location
                location_elem = item.select_one("div.job-listing__location")
                location = location_elem.text.strip() if location_elem else "Unknown Location"

                # Description - simplified for now
                desc = f"Job for {title} at {company} in {location}. See link for details."

                jobs.append({
                    "title": title,
                    "company": company,
                    "location": location,
                    "url": job_url,
                    "description": desc
                })
            except Exception as e:
                log(f"[EUROJOBS ERROR] Error parsing job item: {e}")
                continue

        log(f"[SCRAPER] EuroJobs found: {len(jobs)} jobs")
        return jobs

    except Exception as e:
        log(f"[EUROJOBS ERROR] {e}")
        return []

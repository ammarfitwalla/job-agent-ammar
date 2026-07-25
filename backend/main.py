# Main orchestrator
import sys
from utils.emailer import send_remoteok_batch_email
from scrapers import (
    remoteok_scraper,
    weworkremotely_scraper,
)
from match_engine.relevance_engine import filter_jobs
from emails.daily_report import send_daily_report
from utils.logger import log

def main():

    all_jobs = []

    # --------------------
    # 1. SCRAPE JOBS
    # --------------------
    log("[MAIN] Starting scraping jobs...")
    for scraper, name in [
        (remoteok_scraper.scrape_remoteok, "remoteok_scraper"),
        (weworkremotely_scraper.scrape_wwr, "weworkremotely_scraper"),
    ]:
        try:
            jobs = scraper()
            all_jobs.extend(jobs)
        except Exception as e:
            log(f"[ERROR] {name} failed: {e}")
    log(f"[MAIN] Total scraped jobs: {len(all_jobs)}")

    # --------------------
    # 2. FILTER RELEVANT JOBS
    # --------------------
    try:
        relevant_jobs = filter_jobs(all_jobs)
        log(f"[MAIN] Total relevant jobs: {len(relevant_jobs)}")
    except Exception as e:
        log(f"[ERROR] Filtering jobs failed: {e}")
        relevant_jobs = []

    # --------------------
    # 3. EMAIL RESULTS
    # --------------------
    remoteok_weworkremotely_jobs = [
        job for job in relevant_jobs
        if "remoteok.com" in job["url"].lower() or "weworkremotely.com" in job["url"].lower()
    ]

    if remoteok_weworkremotely_jobs:
        send_remoteok_batch_email(remoteok_weworkremotely_jobs)
        log(f"[EMAIL SENT] Total RemoteOK jobs sent: {len(remoteok_weworkremotely_jobs)}")

    # --------------------
    # 4. SEND DAILY REPORT
    # --------------------
    try:
        send_daily_report([])
        log("[MAIN] Workflow completed.")
    except Exception as e:
        log(f"[ERROR] Sending daily report failed: {e}")


if __name__ == "__main__":
    if "--api" in sys.argv:
        import uvicorn
        uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=True)
    else:
        main()

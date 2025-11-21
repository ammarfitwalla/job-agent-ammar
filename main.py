# Main orchestrator
import sys
from scrapers import (
    remoteok_scraper,
    weworkremotely_scraper,
    naukri_scraper,
    gulftalent_scraper,
    eurojobs_scraper
)
from match_engine.relevance_engine import filter_jobs
from cover_letters.generator import generate_cover_letter
from auto_apply.remoteok_apply import apply_remoteok
from sheets.sheets_writer import log_job
from emails.daily_report import send_daily_report
from config import RESUME_PATH, AUTO_APPLY
from utils.logger import log

def main():

    all_jobs = []

    # --------------------
    # 1️⃣ SCRAPE JOBS
    # --------------------
    log("[MAIN] Starting scraping jobs...")
    for scraper, name in [
        (remoteok_scraper.scrape_remoteok, "remoteok_scraper"),
        (weworkremotely_scraper.scrape_wwr, "weworkremotely_scraper"),
        (naukri_scraper.scrape_naukri, "naukri_scraper"),
        (gulftalent_scraper.scrape_gulftalent, "gulftalent_scraper"),
        (eurojobs_scraper.scrape_eurojobs, "eurojobs_scraper")
    ]:
        try:
            jobs = scraper()
            all_jobs.extend(jobs)
        except Exception as e:
            log(f"[ERROR] {name} failed: {e}")

    log(f"[MAIN] Total scraped jobs: {len(all_jobs)}")
    print(f"Total scraped jobs: {len(all_jobs)}")
    sys.exit(0)
    # --------------------
    # 2️⃣ FILTER RELEVANT JOBS
    # --------------------
    try:
        relevant_jobs = filter_jobs(all_jobs)
        log(f"[MAIN] Total relevant jobs: {len(relevant_jobs)}")
    except Exception as e:
        log(f"[ERROR] Filtering jobs failed: {e}")
        relevant_jobs = []

    # --------------------
    # 3️⃣ GENERATE COVER LETTERS & APPLY
    # --------------------
    applied_jobs = []
    for job in relevant_jobs:
        try:
            cl = generate_cover_letter(job)
            job["cover_letter"] = cl
        except Exception as e:
            log(f"[ERROR] Cover letter generation failed for job {job.get('url', '')}: {e}")
            continue

        try:
            log_job(job)
        except Exception as e:
            log(f"[ERROR] Logging job to Google Sheets failed for job {job.get('url', '')}: {e}")

        # Auto-apply (currently demo with RemoteOK)
        # Extend for other sites by adding site-specific apply modules
        if "remoteok.com" in job["url"]:
            try:
                apply_remoteok(job, RESUME_PATH, cl)
                applied_jobs.append(job)
            except Exception as e:
                log(f"[ERROR] Auto-apply failed for job {job.get('url', '')}: {e}")

        if AUTO_APPLY:
            # Extend to other sites similarly
            pass

    # --------------------
    # 4️⃣ SEND DAILY REPORT
    # --------------------
    try:
        send_daily_report(applied_jobs)
        log("[MAIN] Workflow completed.")
    except Exception as e:
        log(f"[ERROR] Sending daily report failed: {e}")


if __name__ == "__main__":
    main()

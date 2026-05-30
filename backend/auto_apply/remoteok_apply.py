# Demo auto-apply script
from .base_apply import open_browser, close_browser, fill_common_fields
from utils.logger import log

def apply_remoteok(job, resume_path, cover_letter_text):
    print("Applying for job: ", job.get('url', ''))
    playwright, browser = open_browser()
    page = browser.new_page()
    try:
        page.goto(job["url"], timeout=60000)
        fill_common_fields(page, job, resume_path, cover_letter_text)
        log(f"[REMOTEOK APPLY] Done for {job['title']} at {job['company']}")
    except Exception as e:
        print("Error applying for job: ", job.get('url', ''))
        log(f"[REMOTEOK APPLY ERROR] {e}")
    finally:
        print("Closing browser")
        close_browser(playwright, browser)

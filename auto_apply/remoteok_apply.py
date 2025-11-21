# Demo auto-apply script
from .base_apply import open_browser, close_browser, fill_common_fields
from utils.logger import log

def apply_remoteok(job, resume_path, cover_letter_text):
    playwright, browser = open_browser()
    page = browser.new_page()
    try:
        page.goto(job["url"], timeout=60000)
        fill_common_fields(page, job, resume_path, cover_letter_text)
        log(f"[REMOTEOK APPLY] Done for {job['title']} at {job['company']}")
    except Exception as e:
        log(f"[REMOTEOK APPLY ERROR] {e}")
    finally:
        close_browser(playwright, browser)

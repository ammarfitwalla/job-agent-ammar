# Common form filling
from playwright.sync_api import sync_playwright
from config import AUTO_APPLY, SENDER_EMAIL, CHROME_PROFILE_PATH
from utils.logger import log
import time
import os

def open_browser():
    playwright = sync_playwright().start()
    browser = playwright.chromium.launch_persistent_context(
        user_data_dir=CHROME_PROFILE_PATH or os.path.expanduser("~/.job_agent_chrome"),
        headless=False
    )
    return playwright, browser

def close_browser(playwright, browser):
    browser.close()
    playwright.stop()


def fill_common_fields(page, job, resume_path, cover_letter_text):
    """
    Fills name/email/resume/cover letter fields on most job forms.
    """
    try:
        # Example selectors — may need site-specific adjustments
        if page.query_selector('input[name="name"]'):
            page.fill('input[name="name"]', "Ammar Fitwalla")
        if page.query_selector('input[name="email"]'):
            page.fill('input[name="email"]', SENDER_EMAIL)
        if page.query_selector('input[type="file"]'):
            page.set_input_files('input[type="file"]', resume_path)
        if page.query_selector('textarea[name="cover_letter"]'):
            page.fill('textarea[name="cover_letter"]', cover_letter_text)

        log(f"[APPLY] Filled common fields for {job['title']} at {job['company']}")

    except Exception as e:
        log(f"[APPLY ERROR] {e}")

    if not AUTO_APPLY:
        log("[APPLY] Waiting for manual submit...")
        input("Press Enter after manually reviewing and submitting the form...")
    else:
        try:
            if page.query_selector('button[type="submit"]'):
                page.click('button[type="submit"]')
                log("[APPLY] Submitted application automatically")
                time.sleep(2)
        except:
            log("[APPLY] No submit button detected")

# Sends daily Gmail report
import yagmail
from config import SENDER_EMAIL, DAILY_EMAIL_SUBJECT
from utils.logger import log

def send_daily_report(applied_jobs: list):
    if not applied_jobs:
        log("[EMAIL] No jobs to report")
        return

    try:
        body = "Daily Job Application Report:\n\n"
        for job in applied_jobs:
            body += f"{job['title']} at {job['company']} ({job['url']})\n"

        yag = yagmail.SMTP(SENDER_EMAIL)
        yag.send(to=SENDER_EMAIL, subject=DAILY_EMAIL_SUBJECT, contents=body)
        log("[EMAIL] Daily report sent successfully")
    except Exception as e:
        log(f"[EMAIL ERROR] {e}")

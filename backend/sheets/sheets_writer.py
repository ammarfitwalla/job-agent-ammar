# Logs applied jobs to Google Sheets
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from config import GOOGLE_SHEET_NAME
from utils.logger import log

# Google Sheets setup
scope = ["https://spreadsheets.google.com/feeds",
         "https://www.googleapis.com/auth/spreadsheets",
         "https://www.googleapis.com/auth/drive.file",
         "https://www.googleapis.com/auth/drive"]

def get_sheet():
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name("sheets/google_auth.json", scope)
        client = gspread.authorize(creds)
        sheet = client.open(GOOGLE_SHEET_NAME).sheet1
        return sheet
    except Exception as e:
        log(f"[SHEETS ERROR] {e}")
        return None

def log_job(job):
    sheet = get_sheet()
    if not sheet:
        return

    try:
        sheet.append_row([
            job.get("title", ""),
            job.get("company", ""),
            job.get("location", ""),
            job.get("url", ""),
            job.get("total_score", ""),
            job.get("reason", ""),
        ])
        log(f"[SHEETS] Logged job: {job['title']} at {job['company']}")
    except Exception as e:
        log(f"[SHEETS ERROR] {e}")

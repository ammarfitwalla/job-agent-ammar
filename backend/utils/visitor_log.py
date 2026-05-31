import csv
import os
import smtplib
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email import encoders
from datetime import datetime
import config

LOG_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "visitors.csv")
MAX_ROWS = 5
MAX_SIZE = 10 * 1024  # 10KB


def log_visitor(ip: str, path: str, user_agent: str, referer: str = ""):
    timestamp = datetime.utcnow().isoformat()
    row = [timestamp, ip, path, user_agent, referer]

    file_exists = os.path.isfile(LOG_FILE)
    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["timestamp", "ip", "path", "user_agent", "referer"])
        writer.writerow(row)

    _check_threshold()


def _check_threshold():
    if not os.path.isfile(LOG_FILE):
        return

    size = os.path.getsize(LOG_FILE)
    if size < MAX_SIZE:
        with open(LOG_FILE, newline="", encoding="utf-8") as f:
            row_count = sum(1 for _ in f)
        if row_count <= MAX_ROWS:
            return

    _email_log()


def _email_log():
    if not os.path.isfile(LOG_FILE) or os.path.getsize(LOG_FILE) == 0:
        return

    try:
        sender = config.EMAIL_USER
        password = config.EMAIL_PASSWORD
        receiver = config.EMAIL_TO

        msg = MIMEMultipart()
        msg["From"] = sender
        msg["To"] = receiver
        msg["Subject"] = f"Visitor Log — {datetime.utcnow().strftime('%Y-%m-%d')}"

        with open(LOG_FILE, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f"attachment; filename=visitors.csv")
            msg.attach(part)

        body = MIMEText(f"Visitor log attached ({os.path.getsize(LOG_FILE)} bytes, prior to reset).", "plain")
        msg.attach(body)

        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(sender, password)
            server.sendmail(sender, receiver, msg.as_string())

        # Clear the log
        open(LOG_FILE, "w").close()
    except Exception as e:
        print(f"[VISITOR LOG] Email failed: {e}")

import csv
import os
from datetime import datetime

LOG_FILE = os.path.join(os.path.sep, "tmp", "visitors.csv")


def log_visitor(ip: str, path: str, user_agent: str, referer: str = ""):
    timestamp = datetime.utcnow().isoformat()
    row = [timestamp, ip, path, user_agent, referer]

    file_exists = os.path.isfile(LOG_FILE)
    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["timestamp", "ip", "path", "user_agent", "referer"])
        writer.writerow(row)

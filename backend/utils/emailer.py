import os
import requests
from requests.auth import HTTPBasicAuth

MAILJET_API_KEY = os.environ.get("MAILJET_API_KEY", "")
MAILJET_SECRET_KEY = os.environ.get("MAILJET_SECRET_KEY", "")
MAILJET_FROM_EMAIL = os.environ.get("MAILJET_FROM_EMAIL", "noreply@jobagent.brevo.com")


def _mailjet_send(to_email: str, subject: str, html: str):
    r = requests.post(
        "https://api.mailjet.com/v3.1/send",
        auth=HTTPBasicAuth(MAILJET_API_KEY, MAILJET_SECRET_KEY),
        json={
            "Messages": [
                {
                    "From": {"Email": MAILJET_FROM_EMAIL, "Name": "AI Job Agent"},
                    "To": [{"Email": to_email}],
                    "Subject": subject,
                    "HTMLPart": html,
                }
            ]
        },
    )
    if r.status_code >= 400:
        print(f"Mailjet error {r.status_code}: {r.text}")
    r.raise_for_status()


def send_remoteok_batch_email(jobs):
    print("Sending email via Mailjet...")
    subject = f"{len(jobs)} New RemoteOK Jobs Found 🚀"
    body = "🚀 Your RemoteOK Job Summary<br><br>"
    for job in jobs:
        body += f"""
📌 {job.get('title', 'No Title')}<br>
🔗 {job.get('url', '')}<br><br>
🤖 AI Score: {job.get('ai_score', 0)}<br>
🧩 Keyword Score: {job.get('keyword_score', 0)}<br>
📊 Total Score: {job.get('total_score', 0)}<br><br>
📝 Reason:<br>{job.get('reason', 'No reason provided.')}<br><br>
----------------------------------------------<br>
"""
    _mailjet_send(os.environ.get("EMAIL_TO", ""), subject, body)
    print(f"Email sent: {len(jobs)} jobs")


def send_verification_code(email: str, code: str):
    html = f"Your verification code is:<br><br><strong>{code}</strong><br><br>This code expires in 10 minutes.<br><br>If you didn't request this, you can safely ignore this email."
    _mailjet_send(email, "Your Job Agent verification code", html)

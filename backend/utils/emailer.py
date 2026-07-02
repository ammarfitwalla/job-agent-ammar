import os
import requests

BREVO_API_KEY = os.environ.get("BREVO_API_KEY", "")
BREVO_FROM_EMAIL = os.environ.get("BREVO_FROM_EMAIL", "noreply@jobagent.brevo.com")


def _brevo_send(to_email: str, subject: str, html: str):
    r = requests.post(
        "https://api.brevo.com/v3/smtp/email",
        headers={
            "api-key": BREVO_API_KEY,
            "Content-Type": "application/json",
        },
        json={
            "sender": {"email": BREVO_FROM_EMAIL},
            "to": [{"email": to_email}],
            "subject": subject,
            "htmlContent": html,
        },
    )
    if r.status_code >= 400:
        print(f"Brevo error {r.status_code}: {r.text}")
    r.raise_for_status()


def send_remoteok_batch_email(jobs):
    print("Sending email via Brevo...")
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
    _brevo_send(os.environ.get("EMAIL_TO", ""), subject, body)
    print(f"Email sent: {len(jobs)} jobs")


def send_verification_code(email: str, code: str):
    html = f"Your verification code is:<br><br><strong>{code}</strong><br><br>This code expires in 10 minutes.<br><br>If you didn't request this, you can safely ignore this email."
    _brevo_send(email, "Your Job Agent verification code", html)

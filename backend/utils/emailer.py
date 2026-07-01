import resend
from config import EMAIL_TO, RESEND_API_KEY, RESEND_FROM_EMAIL

resend.api_key = RESEND_API_KEY

def send_remoteok_batch_email(jobs):
    print("Sending email via Resend...")
    from_email = RESEND_FROM_EMAIL

    subject = f"{len(jobs)} New RemoteOK Jobs Found 🚀"

    body = "🚀 Your RemoteOK Job Summary\n\n"

    for job in jobs:
        body += f"""
📌 {job.get('title', 'No Title')}
🔗 {job.get('url', '')}

🤖 AI Score: {job.get('ai_score', 0)}
🧩 Keyword Score: {job.get('keyword_score', 0)}
📊 Total Score: {job.get('total_score', 0)}

📝 Reason:
{job.get('reason', 'No reason provided.')}

📃 Description:
{job.get('description', '')[:2000]}

----------------------------------------------
"""

    r = resend.Emails.send({
        "from": from_email,
        "to": EMAIL_TO,
        "subject": subject,
        "html": body.replace("\n", "<br>"),
    })
    print(f"Email sent: {len(jobs)} jobs")


def send_verification_code(email: str, code: str):
    from_email = RESEND_FROM_EMAIL

    body = f"Your verification code is:<br><br><strong>{code}</strong><br><br>This code expires in 10 minutes.<br><br>If you didn't request this, you can safely ignore this email."

    r = resend.Emails.send({
        "from": from_email,
        "to": email,
        "subject": "Your Job Agent verification code",
        "html": body,
    })
    if hasattr(r, "error") and r.error:
        print(f"Resend error: {r.error}")

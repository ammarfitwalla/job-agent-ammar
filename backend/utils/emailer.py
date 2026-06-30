import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import config

def send_remoteok_batch_email(jobs):
    print("Sending email...")
    sender = config.EMAIL_USER
    password = config.EMAIL_PASSWORD
    receiver = config.EMAIL_TO

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

    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = receiver
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(sender, password)
        server.sendmail(sender, receiver, msg.as_string())


def send_verification_code(email: str, code: str):
    sender = config.EMAIL_USER
    password = config.EMAIL_PASSWORD

    subject = "Your Job Agent verification code"
    body = f"""
Your verification code is:

  {code}

This code expires in 10 minutes.

If you didn't request this, you can safely ignore this email.
"""

    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(sender, password)
        server.sendmail(sender, email, msg.as_string())

import smtplib
from email.mime.text import MIMEText
import logging

log = logging.getLogger(__name__)


def send_email(to: str, subject: str, html_body: str) -> bool:
    """Send email via Gmail SMTP. Returns True on success."""
    try:
        from config import EMAIL_HOST, EMAIL_PORT, EMAIL_USER, EMAIL_PASSWORD
        if not all([EMAIL_HOST, EMAIL_PORT, EMAIL_USER, EMAIL_PASSWORD]):
            log.warning("SMTP config incomplete, skipping")
            return False
        msg = MIMEText(html_body, "html")
        msg["Subject"] = subject
        msg["From"] = EMAIL_USER
        msg["To"] = to
        with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT, timeout=10) as s:
            s.starttls()
            s.login(EMAIL_USER, EMAIL_PASSWORD)
            s.send_message(msg)
        log.info(f"SMTP email sent to {to}")
        return True
    except Exception as e:
        log.warning(f"SMTP failed for {to}: {e}")
        return False


def send_verification_email(to: str, code: str) -> bool:
    """Send 6-digit verification code via SMTP."""
    html = (
        "<div style='font-family:sans-serif;max-width:400px;margin:0 auto;padding:20px'>"
        "<h2 style='color:#1e293b'>Job Agent</h2>"
        "<p style='color:#475569'>Your verification code:</p>"
        f"<p style='font-size:28px;font-weight:bold;letter-spacing:4px;color:#1e293b'>{code}</p>"
        "<p style='color:#94a3b8;font-size:13px'>Expires in 10 minutes.</p>"
        "</div>"
    )
    return send_email(to, "Job Agent — Your Verification Code", html)

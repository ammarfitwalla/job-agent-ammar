import smtplib
import gzip
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import logging
import os

log = logging.getLogger(__name__)


def _send_msg_with_retry(msg, to, tries=3, timeout=120):
    """Send via Gmail SMTP with a generous timeout and retries on drop.

    Large attachments make Gmail occasionally kill the connection mid-upload
    (SMTPServerDisconnected); a fresh connection on retry resolves it."""
    from config import EMAIL_HOST, EMAIL_PORT, EMAIL_USER, EMAIL_PASSWORD
    if not all([EMAIL_HOST, EMAIL_PORT, EMAIL_USER, EMAIL_PASSWORD]):
        log.warning("SMTP config incomplete, skipping")
        return False
    for attempt in range(1, tries + 1):
        try:
            with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT, timeout=timeout) as s:
                s.starttls()
                s.login(EMAIL_USER, EMAIL_PASSWORD)
                s.send_message(msg)
            log.info(f"SMTP email sent to {to}")
            return True
        except Exception as e:
            log.warning(f"SMTP attempt {attempt}/{tries} failed for {to}: {e}")
    log.warning(f"SMTP failed for {to}")
    return False


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
        return _send_msg_with_retry(msg, to)
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


def send_email_with_attachment(to: str, subject: str, html_body: str, file_path: str, filename: str) -> bool:
    """Send email with a file attachment via Gmail SMTP. Returns True on success."""
    try:
        from config import EMAIL_HOST, EMAIL_PORT, EMAIL_USER, EMAIL_PASSWORD
        if not all([EMAIL_HOST, EMAIL_PORT, EMAIL_USER, EMAIL_PASSWORD]):
            log.warning("SMTP config incomplete, skipping")
            return False
        msg = MIMEMultipart()
        msg["Subject"] = subject
        msg["From"] = EMAIL_USER
        msg["To"] = to
        msg.attach(MIMEText(html_body, "html"))
        with open(file_path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{filename}"')
        msg.attach(part)
        return _send_msg_with_retry(msg, to)
    except Exception as e:
        log.warning(f"SMTP attachment failed for {to}: {e}")
        return False

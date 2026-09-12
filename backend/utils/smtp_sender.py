import smtplib
import gzip
import html
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


def send_email(to: str, subject: str, html_body: str, text_body: str | None = None) -> bool:
    """Send email via Gmail SMTP. Returns True on success."""
    try:
        from config import EMAIL_HOST, EMAIL_PORT, EMAIL_USER, EMAIL_PASSWORD
        if not all([EMAIL_HOST, EMAIL_PORT, EMAIL_USER, EMAIL_PASSWORD]):
            log.warning("SMTP config incomplete, skipping")
            return False
        msg = MIMEMultipart("alternative") if text_body else MIMEText(html_body, "html")
        if text_body:
            msg.attach(MIMEText(text_body, "plain"))
            msg.attach(MIMEText(html_body, "html"))
        msg["Subject"] = subject
        msg["From"] = EMAIL_USER
        msg["To"] = to
        return _send_msg_with_retry(msg, to)
    except Exception as e:
        log.warning(f"SMTP failed for {to}: {e}")
        return False


def send_verification_email(to: str, code: str) -> bool:
    """Send 6-digit verification code via SMTP."""
    email = html.escape(to)
    html_body = (
        "<div style='font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;"
        "background-color:#f8fafc;padding:32px 16px'>"
        "<div style='max-width:480px;margin:0 auto;background-color:#ffffff;border-radius:16px;"
        "border:1px solid #e2e8f0;overflow:hidden'>"
        f"<div style='background:linear-gradient(135deg,#4f46e5,#6366f1);padding:24px 28px;text-align:center'>"
        "<div style='color:#ffffff;font-size:26px;font-weight:800;letter-spacing:-0.5px'>JobAwn</div>"
        "<div style='color:#c7d2fe;font-size:13px;margin-top:2px'>Verify your email address</div>"
        "</div>"
        f"<div style='padding:28px'>"
        f"<p style='color:#1e293b;font-size:15px;margin:0 0 4px 0'>Hi there,</p>"
        f"<p style='color:#475569;font-size:14px;margin:0 0 20px 0;line-height:1.5'>"
        f"Use the code below to finish signing in to JobAwn.</p>"
        f"<div style='margin:0 0 20px 0;border:2px dashed #c7d2fe;border-radius:12px;background-color:#eef2ff;"
        f"padding:18px;text-align:center;cursor:pointer;-webkit-user-select:all;user-select:all'>"
        f"<div style='font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:34px;font-weight:700;"
        f"letter-spacing:8px;color:#4338ca'>{code}</div>"
        "</div>"
        "<p style='color:#64748b;font-size:13px;margin:0 0 6px 0'>"
        "This code expires in <strong>10 minutes</strong> and is only valid for "
        f"<strong style='color:#475569'>{email}</strong>.</p>"
        "<p style='color:#94a3b8;font-size:12px;margin:0;line-height:1.5'>"
        "If you didn't request this code, you can safely ignore this email — your account stays protected."
        " JobAwn will never ask you for this code. Never share it with anyone.</p>"
        "</div>"
        "<div style='background-color:#f8fafc;border-top:1px solid #e2e8f0;padding:14px 28px;text-align:center'>"
        "<p style='color:#94a3b8;font-size:12px;margin:0'>JobAwn · <a href='https://jobawn.com' "
        "style='color:#6366f1;text-decoration:none'>jobawn.com</a></p>"
        "</div>"
        "</div>"
        "</div>"
    )
    text_body = (
        "JobAwn — Verify your email address\n\n"
        "Hi there,\n\n"
        f"Use the code below to finish signing in to JobAwn:\n\n  {code}\n\n"
        f"This code expires in 10 minutes and is only valid for {to}.\n\n"
        "If you didn't request this code, you can safely ignore this email. "
        "JobAwn will never ask you for this code. Never share it with anyone.\n\n"
        "— JobAwn (jobawn.com)"
    )
    return send_email(to, "JobAwn — Your Verification Code", html_body, text_body)


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

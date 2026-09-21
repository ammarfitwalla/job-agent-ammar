"""SendCoreX HTTP API sender (https://mail.sendcorex.com/v3.0/send).

Used when config.EMAIL_PROVIDER == "sendcorex_api".
"""
# import base64
import logging
# import mimetypes
import os
import re

import requests

log = logging.getLogger(__name__)

_SEND_URL = os.environ.get("SENDCOREX_API_URL", "https://mail.sendcorex.com/v3.0/send")
_TIMEOUT = 30


def _split_from():
    from config import EMAIL_FROM
    addr = (EMAIL_FROM or "").strip()
    m = re.match(r"^(.*?)\s*<([^>]+)>$", addr)
    if m:
        return m.group(2).strip(), (m.group(1).strip() or "JobAwn")
    return addr or "", "JobAwn"


# def _attachment(file_path, filename):
#     """Standard base64 attachment object (base64 content, mime-sniffed type)."""
#     with open(file_path, "rb") as f:
#         content = base64.b64encode(f.read()).decode("ascii")
#     ctype = mimetypes.guess_type(filename or file_path)[0] or "application/octet-stream"
#     return {"filename": filename or os.path.basename(file_path), "content": content, "contentType": ctype}


def send(to, subject, html_body, file_path=None, filename=None, transactional=True, reply_to=None):
    """Send via the SendCoreX /v3.0/send endpoint. Returns True on queue.

    Attachments are not supported in this API path — file_path/filename are
    accepted for signature compatibility but ignored.
    """
    from config import SENDCORE_API_KEY, EMAIL_REPLY_TO
    if not SENDCORE_API_KEY:
        log.warning("SENDCORE_API_KEY not set, skipping")
        return False

    from_email, sender_name = _split_from()
    payload = {
        "to": to,
        "from": from_email,
        "senderName": sender_name,
        "subject": subject,
        "body": html_body,
        "transactional": bool(transactional),
    }
    if reply_to:
        payload["replyTo"] = reply_to
    elif EMAIL_REPLY_TO:
        payload["replyTo"] = EMAIL_REPLY_TO
    # if file_path:
    #     payload["attachments"] = [_attachment(file_path, filename)]

    try:
        r = requests.post(
            _SEND_URL,
            json=payload,
            headers={"Authorization": SENDCORE_API_KEY, "Content-Type": "application/json"},
            timeout=_TIMEOUT,
        )
    except Exception as e:
        log.warning(f"SendCoreX request failed for {to}: {e}")
        return False

    if r.status_code in (200, 202):
        try:
            msg_id = r.json().get("id", "")
        except Exception:
            msg_id = ""
        log.info(f"SendCoreX email queued to {to}" + (f" (id={msg_id})" if msg_id else ""))
        return True

    log.warning(f"SendCoreX send failed ({r.status_code}) for {to}: {r.text[:300]}")
    return False
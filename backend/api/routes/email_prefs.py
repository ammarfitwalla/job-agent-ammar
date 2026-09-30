from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

_DONE_HTML = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Unsubscribed</title></head>
<body style="margin:0;min-height:100vh;background:#f8fafc;display:flex;align-items:center;justify-content:center;font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif">
  <div style="text-align:center;padding:24px">
    <div style="font-size:28px;font-weight:800;letter-spacing:-0.03em;color:#1e293b">You're unsubscribed</div>
    <div style="font-size:15px;font-weight:600;color:#64748b;margin-top:8px;max-width:420px">
      You'll no longer get weekly job-update emails about JobAwn. You'll still
      receive important account emails like login codes and referral updates.
    </div>
  </div>
</body>
</html>"""

_BAD_SIG_HTML = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Link invalid</title></head>
<body style="margin:0;min-height:100vh;background:#f8fafc;display:flex;align-items:center;justify-content:center;font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif">
  <div style="text-align:center;padding:24px">
    <div style="font-size:28px;font-weight:800;letter-spacing:-0.03em;color:#1e293b">Link invalid</div>
    <div style="font-size:15px;font-weight:600;color:#64748b;margin-top:8px">
      This unsubscribe link is no longer valid. Open the latest email from JobAwn
      and use its link instead.
    </div>
  </div>
</body>
</html>"""


@router.get("/api/email/unsubscribe", response_class=HTMLResponse)
async def unsubscribe(email: str = "", s: str = ""):
    from emails.unsubscribe import validate_unsubscribe
    from db import set_user_email_opt_out
    if not validate_unsubscribe(email, s):
        return HTMLResponse(_BAD_SIG_HTML, status_code=400)
    set_user_email_opt_out(email, True)
    return HTMLResponse(_DONE_HTML)
"""JobAwn automated-email template builders.

Each builder returns (subject, html_body, text_body, utm_campaign) and MUST
html.escape dynamic input. Visual tokens come from emails.tokens only —
see docs/planning/EMAIL_DESIGN_SPEC.md."""

import html

from emails.tokens import PALETTE, LAYOUT, button_html

_ESC = html.escape


# ── shared shell (5-zone layout) ──────────────────────────────────────────


def _url(path: str, campaign: str) -> str:
    return f"https://jobawn.com{path}?utm_campaign={_ESC(campaign, quote=True)}&utm_source=email"


def _first_name(name: str) -> str:
    parts = (name or "").strip().split()
    return parts[0] if parts else ""


def _build_html(subtitle: str, body_html: str, cta_text: str, cta_url: str,
                why_line: str) -> str:
    p = PALETTE
    return (
        f"<div style='font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;"
        f"background-color:{p['brand-page']};padding:32px 16px'>"
        f"<div style='max-width:{LAYOUT['max_width']}px;margin:0 auto;background-color:{p['brand-card']};"
        f"border-radius:{LAYOUT['card_radius']}px;border:1px solid {p['brand-divider']};overflow:hidden'>"
        # Zone A — Header
        f"<div style='background:{LAYOUT['header_gradient']};padding:24px 28px;text-align:center'>"
        "<div style='color:#ffffff;font-size:26px;font-weight:800;letter-spacing:-0.5px'>JobAwn</div>"
        f"<div style='color:{p['brand-border']};font-size:13px;margin-top:2px'>{_ESC(subtitle)}</div>"
        "</div>"
        # Zone B — Body
        f"<div style='padding:{LAYOUT['body_padding']}'>"
        + body_html
        + "</div>"
        # Zone C — CTA
        + button_html(cta_text, cta_url)
        # Zone D — Meta / why-you-got-this
        + f"<div style='padding:0 28px 20px 28px'><p style='color:{p['brand-muted']};font-size:13px;"
        f"line-height:1.5;margin:0'>{_ESC(why_line)}</p></div>"
        # Zone E — Footer
        f"<div style='background-color:{p['brand-page']};border-top:1px solid {p['brand-divider']};"
        f"padding:14px 28px;text-align:center'>"
        f"<p style='color:{p['brand-faint']};font-size:12px;margin:0'>JobAwn · "
        "<a href='https://jobawn.com' style='color:#6366f1;text-decoration:none'>jobawn.com</a></p>"
        "</div>"
        "</div>"
        "</div>"
    )


def _chip(text: str, color: str) -> str:
    return (
        f"<div style='display:inline-block;color:{color};font-size:12px;font-weight:700;"
        "letter-spacing:1px;text-transform:uppercase;margin-bottom:8px'>"
        f"{_ESC(text)}</div>"
    )


def _info_box(lines_html: str) -> str:
    p = PALETTE
    return (
        f"<div style='margin:0 0 20px 0;border:2px dashed {p['brand-border']};border-radius:12px;"
        f"background-color:{p['brand-elevate']};padding:16px 18px;font-size:14px;color:{p['brand-body']};"
        f"line-height:1.6'>{lines_html}</div>"
    )


def _greeting(name: str) -> str:
    fn = _first_name(name)
    return f"Hi {_ESC(fn)}," if fn else "Hi there,"


def _paragraph(text: str) -> str:
    p = PALETTE
    return (f"<p style='color:{p['brand-body']};font-size:14px;margin:0 0 14px 0;"
            f"line-height:1.5'>{text}</p>")


# ── template builders ─────────────────────────────────────────────────────


def build_welcome(name: str) -> tuple[str, str, str, str]:
    subject = "JobAwn — Welcome to JobAwn"
    campaign = "welcome"
    fn = _first_name(name)
    body = (
        _greeting(name)
        + f"<div style='color:{PALETTE['brand-ink']};font-size:18px;font-weight:700;"
        f"margin:0 0 12px 0'>Welcome to JobAwn!</div>"
        "JobAwn finds the jobs that actually fit your skills and keeps relevant "
        "opportunities warm 24/7 — so when you search, results are fresh."
        "<br/><br/>Three quick steps to get the most out of JobAwn:<br/>"
        + _info_box(
            "<strong>1.</strong> Upload your resume — every job you'll see shows how well "
            "it matches you.<br/>"
            "<strong>2.</strong> Search the roles you're targeting — we keep those jobs "
            "warm and fresh in your dashboard around the clock.<br/>"
            "<strong>3.</strong> Turn on \"notify me\" for the companies you're aiming at — "
            "we'll email you the moment someone there is open to referrals."
        )
        + "<p style='margin:0'>If you need anything, just reply to this email.</p>"
    )
    why = "You're receiving this because you just created a JobAwn account. Log in to jobawn.com to manage your profile and notifications."
    text = (
        f"Hi {fn or 'there'},\n\n"
        "Welcome to JobAwn!\n\n"
        "JobAwn finds the jobs that actually fit your skills and keeps relevant "
        "opportunities warm 24/7 — so when you search, results are fresh.\n\n"
        "Three quick steps:\n"
        "1. Upload your resume — every job you'll see shows how well it matches you.\n"
        "2. Search the roles you're targeting — we keep those jobs warm and fresh in "
        "your dashboard around the clock.\n"
        "3. Turn on \"notify me\" for the companies you're aiming at — we'll email you "
        "the moment someone there is open to referrals.\n\n"
        f"{why}\n\n— JobAwn (https://jobawn.com)"
    )
    html = _build_html("Your account is ready", body, "Start searching jobs",
                       _url("/app", campaign), why)
    return subject, html, text, campaign


def build_referral_requested(name: str, job_title: str, company: str,
                             match_score: int, message: str) -> tuple[str, str, str, str]:
    title = job_title or "a role"
    company = company or "a company"
    subject = f"JobAwn — Referral request: {title}"
    campaign = "referral_requested"

    info_lines = (
        f"<div style='font-size:15px;font-weight:700;color:{PALETTE['brand-ink']}'>"
        f"{_ESC(title)}</div>"
        f"<div>at <strong>{_ESC(company)}</strong></div>"
    )
    if match_score and match_score > 0:
        info_lines += _chip(f"Match score {match_score}/100", PALETTE["brand-success"])
    if message and message.strip():
        info_lines += (
            f"<div style='margin-top:10px;color:{PALETTE['brand-muted']};font-style:italic'>"
            f"\"{_ESC(message.strip())}\"</div>"
        )

    body = (
        _greeting(name)
        + f"<div style='color:{PALETTE['brand-ink']};font-size:18px;font-weight:700;"
        "margin:0 0 12px 0'>Someone asked you for a referral</div>"
        + _paragraph(
            "A professional on JobAwn believes you could help them at " +
            "<strong>" + _ESC(company) + "</strong>. The job matched their resume "
            "well, so they're reaching out for a referral."
        )
        + "<p style='margin:0 0 14px 0'>Here's what they're asking about:</p>"
        + _info_box(info_lines)
        + _paragraph("Review the request, and if it works, accept it — they'll see your "
                     "contact details to follow up. You can decline anytime; it won't "
                     "affect your standing.")
    )
    why = ("You're receiving this because you're opted in as an open referrer at "
           f"{company} on JobAwn. Manage your availability in your profile.")
    text = (
        f"Hi {_first_name(name) or 'there'},\n\n"
        "Someone asked you for a referral.\n\n"
        f"Role: {title}\nCompany: {company}\n"
        + (f"Match score: {match_score}/100\n" if match_score and match_score > 0 else "")
        + (f"Their message: \"{message.strip()}\"\n" if message and message.strip() else "")
        + "\nSign in to review and accept or decline the request:\n"
        "https://jobawn.com/app#referrals\n\n"
        f"{why}\n\n— JobAwn (https://jobawn.com)"
    )
    html = _build_html("Referral request", body, "Review request",
                       _url("/app#referrals", campaign), why)
    return subject, html, text, campaign


def build_referral_accepted(name: str, referrer_name: str, company: str,
                            position: str, linkedin_url: str) -> tuple[str, str, str, str]:
    ref_first = _first_name(referrer_name) or "your referrer"
    subject = f"JobAwn — {ref_first} accepted your referral request"
    campaign = "referral_accepted"

    contact_lines = (
        f"<div style='font-size:15px;font-weight:700;color:{PALETTE['brand-ink']}'>"
        f"{_ESC(referrer_name or 'Your referrer')}</div>"
        f"<div>{_ESC(position or '')}{' at ' + _ESC(company) if company else ''}</div>"
    )
    if linkedin_url and linkedin_url.strip():
        contact_lines += (
            f"<div style='margin-top:10px'><a href='{_ESC(linkedin_url.strip(), quote=True)}' "
            f"style='color:{PALETTE['brand-primary']};text-decoration:none'>View on LinkedIn</a></div>"
        )

    body = (
        _greeting(name)
        + f"<div style='color:{PALETTE['brand-ink']};font-size:18px;font-weight:700;"
        "margin:0 0 12px 0'>Great news — your referral request was accepted</div>"
        + _paragraph(
            f"<strong>{_ESC(referrer_name or 'Your referrer')}</strong> from " +
            f"<strong>{_ESC(company) if company else 'their company'}</strong> accepted "
            "your request and you can now reach them directly."
        )
        + "<p style='margin:0 0 14px 0'>Their contact details:</p>"
        + _info_box(contact_lines)
        + _paragraph("Send a short message about the role, attach anything they need, "
                     "and once things move forward they'll complete the referral on "
                     "their side.")
    )
    why = ("You're receiving this because you asked for a referral on JobAwn. "
           "You can track the request in your dashboard.")
    text = (
        f"Hi {_first_name(name) or 'there'},\n\n"
        "Great news — your referral request was accepted.\n\n"
        f"{referrer_name or 'Your referrer'} from {company or 'their company'} is now "
        "ready to connect with you.\n"
        f"Contact: {referrer_name or ''}"
        + (f" — {position}" if position else "")
        + (f" ({linkedin_url})" if linkedin_url and linkedin_url.strip() else "")
        + "\n\nSign in to view next steps:\nhttps://jobawn.com/app#referrals\n\n"
        f"{why}\n\n— JobAwn (https://jobawn.com)"
    )
    html = _build_html("Referral accepted", body, "View contact & next steps",
                       _url("/app#referrals", campaign), why)
    return subject, html, text, campaign


def build_confirm_reminder_receiver(name: str, seeker_name: str,
                                    company: str) -> tuple[str, str, str, str]:
    """Cooldown-end nudge to the referrer (receiver of the request): did the
    referral actually happen? Confirm to earn +10 credits once both sides do."""
    seeker = seeker_name or "a seeker"
    comp = company or "their company"
    seeker_first = _first_name(seeker_name) or seeker
    subject = f"JobAwn — Did you refer {seeker_first} at {comp}?"
    campaign = "confirm_reminder"
    body = (
        _greeting(name)
        + f"<div style='color:{PALETTE['brand-ink']};font-size:18px;font-weight:700;"
        "margin:0 0 12px 0'>Time to confirm your referral</div>"
        + _paragraph(
            f"Your referral for <strong>{_ESC(seeker)}</strong> at "
            f"<strong>{_ESC(comp)}</strong> has reached the confirmation window."
        )
        + _paragraph(
            f"Did you actually refer <strong>{_ESC(seeker)}</strong>? "
            "Confirm the referral so it can be closed out on both sides — once "
            "they confirm too, you'll earn <strong>+10 JobAwn credits</strong>."
        )
        + _paragraph(
            "Confirm only if the referral really happened. If it fell through, "
            "you can withdraw instead — the request closes without needing "
            "anything else from you."
        )
    )
    why = ("You're receiving this because you accepted a referral request on "
           "JobAwn. Confirm whether the referral happened so both sides can "
           "close it out.")
    text = (
        f"Hi {_first_name(name) or 'there'},\n\n"
        "Time to confirm your referral.\n\n"
        f"Your referral for {seeker} at {comp} has reached the confirmation window.\n\n"
        "Did you actually refer them? Confirm the referral so it can be closed "
        "out on both sides — once they confirm too, you'll earn +10 JobAwn credits.\n\n"
        "Sign in to confirm:\n"
        "https://jobawn.com/app#referrals\n\n"
        f"{why}\n\n— JobAwn (https://jobawn.com)"
    )
    html = _build_html("Confirm your referral", body, "Confirm referral",
                       _url("/app#referrals", campaign), why)
    return subject, html, text, campaign


def build_confirm_reminder_sender(name: str, referrer_name: str,
                                  company: str) -> tuple[str, str, str, str]:
    """Cooldown-end nudge to the seeker (sender of the request): confirm whether
    the referrer actually referred them, so the referral can be closed out."""
    referrer = referrer_name or "your referrer"
    comp = company or "their company"
    referrer_first = _first_name(referrer_name) or referrer
    subject = f"JobAwn — Did {referrer_first} refer you at {comp}?"
    campaign = "confirm_reminder"
    body = (
        _greeting(name)
        + f"<div style='color:{PALETTE['brand-ink']};font-size:18px;font-weight:700;"
        "margin:0 0 12px 0'>Time to confirm your referral</div>"
        + _paragraph(
            f"The referral you asked for from <strong>{_ESC(referrer)}</strong> at "
            f"<strong>{_ESC(comp)}</strong> has reached the confirmation window."
        )
        + _paragraph(
            f"Did <strong>{_ESC(referrer)}</strong> actually refer you for the role? "
            "Confirm the outcome — when it matches what they report, the referral "
            "is officially complete."
        )
        + _paragraph(
            "If the referral didn't happen, confirm that instead, so the request "
            "closes out cleanly either way."
        )
    )
    why = ("You're receiving this because you asked for a referral on JobAwn. "
           "Confirm the outcome in your dashboard so the request can close out.")
    text = (
        f"Hi {_first_name(name) or 'there'},\n\n"
        "Time to confirm your referral.\n\n"
        f"The referral you asked for from {referrer} at {comp} has reached the "
        "confirmation window.\n\n"
        f"Did {referrer} actually refer you? Confirm the outcome — when it matches "
        "what they report, the referral is officially complete.\n\n"
        "Sign in to confirm:\n"
        "https://jobawn.com/app#referrals\n\n"
        f"{why}\n\n— JobAwn (https://jobawn.com)"
    )
    html = _build_html("Confirm your referral", body, "Confirm referral",
                       _url("/app#referrals", campaign), why)
    return subject, html, text, campaign


def build_company_joined(name: str, company: str) -> tuple[str, str, str, str]:
    company = company or "your company"
    subject = f"JobAwn — Someone from {company} just joined"
    campaign = "company_joined"

    body = (
        _greeting(name)
        + f"<div style='color:{PALETTE['brand-ink']};font-size:18px;font-weight:700;"
        "margin:0 0 12px 0'>Good news for your job hunt</div>"
        + _paragraph(
            f"A new opted-in professional from <strong>{_ESC(company)}</strong> just "
            "joined JobAwn and is open to referrals."
        )
        + _paragraph(
            "They've registered as an available referrer — so this is a fresh, direct "
            "line into the company on your list."
        )
    )
    why = (f"You're receiving this because you asked JobAwn to alert you when "
           f"professionals from {company} join. You can remove this alert anytime.")
    text = (
        f"Hi {_first_name(name) or 'there'},\n\n"
        f"Good news — a new opted-in professional from {company} just joined JobAwn "
        "and is open to referrals.\n\n"
        "Sign in to find a referrer at " + company + ":\n"
        "https://jobawn.com/app\n\n"
        f"{why}\n\n— JobAwn (https://jobawn.com)"
    )
    html = _build_html("New referrer available", body, f"Find a referrer at {company}",
                       _url("/app", campaign), why)
    return subject, html, text, campaign
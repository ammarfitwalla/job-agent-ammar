"""JobAwn email design tokens — single source of truth for every automated mail.

See docs/planning/EMAIL_DESIGN_SPEC.md. No hex value outside PALETTE may appear
in generated email HTML."""

PALETTE = {
    "brand-primary": "#4f46e5",
    "brand-primary-2": "#6366f1",
    "brand-ink": "#1e293b",
    "brand-body": "#475569",
    "brand-muted": "#64748b",
    "brand-faint": "#94a3b8",
    "brand-elevate": "#eef2ff",
    "brand-border": "#c7d2fe",
    "brand-page": "#f8fafc",
    "brand-card": "#ffffff",
    "brand-divider": "#e2e8f0",
    "brand-success": "#059669",
    "brand-warning": "#d97706",
    "brand-danger": "#dc2626",
}

LAYOUT = {
    "page_bg": PALETTE["brand-page"],
    "card_bg": PALETTE["brand-card"],
    "max_width": 480,
    "card_radius": 16,
    "header_gradient": f"linear-gradient(135deg, {PALETTE['brand-primary']}, {PALETTE['brand-primary-2']})",
    "body_padding": "28px",
}


def button_html(text: str, url: str) -> str:
    """Single primary CTA button block (exactly one per email)."""
    return (
        "<table role='presentation' cellpadding='0' cellspacing='0' style='margin:0 auto 24px auto'>"
        "<tr><td align='center'>"
        f"<a href='{url}' style='display:inline-block;background-color:{PALETTE['brand-primary']};"
        f"color:#ffffff;font-size:15px;font-weight:700;text-decoration:none;border-radius:10px;"
        f"padding:12px 24px;'>"
        + text +
        "</a></td></tr></table>"
    )
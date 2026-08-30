import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from utils.pii import sanitize_resume_text  # noqa: E402


@pytest.mark.parametrize("email", [
    "john.doe@example.com",
    "jane+tag@sub.domain.co",
    "first_last@company-name.io",
    "dev@my-project.tech",
])
def test_email_redacted(email):
    out = sanitize_resume_text(f"Name\nContact: {email}")
    assert email not in out
    assert "[email]" in out


@pytest.mark.parametrize("phone", [
    "(415) 555-0123",
    "987-654-3210",
    "+1-202-555-0145",
    "+91 98765 43210",
    "98200 12345",
    "+44 20 7946 0958",
    "+971 50 123 4567",
    "+61412345678",
])
def test_phone_redacted(phone):
    out = sanitize_resume_text(f"Name\nPhone: {phone}")
    assert phone not in out
    assert "[phone]" in out


@pytest.mark.parametrize("url", [
    "https://www.linkedin.com/in/john-doe",
    "http://github.com/johndoe",
    "www.portfolio.example.io",
    "https://example.com/cv.pdf",
    "linkedin.com/in/john-doe",
    "github.com/johndoe/tools",
])
def test_url_redacted(url):
    out = sanitize_resume_text(f"Name\nLinks: {url}")
    assert url not in out
    assert "[link]" in out


@pytest.mark.parametrize("addr", [
    "123 Main Street, Springfield, IL 62704",
    "46 Park Avenue, New York, NY 10022-4311",
    "09 sneha park, Indiranagar, Bengaluru, Karnataka 560038",
    "B-302 Palm Grove Apartments, Andheri West, Mumbai 400053",
])
def test_address_line_redacted(addr):
    out = sanitize_resume_text(f"Name\nAddress B\n{addr}")
    assert addr not in out
    assert "[address]" in out


def test_name_redacted_and_propagated():
    text = "Ammar Fitwalla\nammar@example.com\n\nSummary of work\n\nCert\n- Verified by Ammar Fitwalla"
    out = sanitize_resume_text(text)
    assert "Ammar Fitwalla" not in out
    assert out.count("[name]") == 2


def test_objective_title_not_redacted_as_name():
    text = "Senior Data Engineer\nPython, AWS\n"
    out = sanitize_resume_text(text)
    assert "Senior Data Engineer" in out
    assert "[name]" not in out


def test_skills_and_dates_preserved():
    text = "Ammar Fitwalla\n\ndanahue@x.io\n\nBuilt REST APIs in Python 3.12 (2021-2025). Team of 20000 at 50000 req/s."
    clean = sanitize_resume_text(text)
    assert "Python 3.12" in clean
    assert "2021-2025" in clean
    assert "Team of 20000" in clean
    assert "50000 req/s" in clean


def test_empty_and_none():
    assert sanitize_resume_text("") == ""
    assert sanitize_resume_text(None) is None


def test_full_realistic_resume_no_pii_left():
    resume = """Ammar Fitwalla
Senior Python Developer | Bengaluru, India | ammar.fitwalla@gmail.com
+91 98765 43210 | (415) 555-0123
https://www.linkedin.com/in/ammar-fitwalla
github.com/ammarfitwalla

SUMMARY
Backend engineer, 8+ years, data pipelines, Python 3.12, Docker.

EXPERIENCE
Acme Corp, Bengaluru - Senior Backend Engineer (2021-2025)
- REST APIs, FastAPI, Postgres 15, Kafka, 1.2 million events/day.

09 sneha park, Indiranagar, Bengaluru, Karnataka 560038
"""
    clean = sanitize_resume_text(resume)
    for secret in ["ammar.fitwalla@gmail.com", "+91 98765 43210", "(415) 555-0123",
                   "linkedin.com", "github.com/ammarfitwalla", "Ammar Fitwalla", "560038"]:
        assert secret not in clean
    for kept in ["Python 3.12", "Acme Corp", "2021-2025", "FastAPI", "1.2 million"]:
        assert kept in clean
    for tag in ["[email]", "[phone]", "[link]", "[name]", "[address]"]:
        assert tag in clean
import re

__all__ = ["sanitize_resume_text"]


_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

_URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_DOMAIN_LINK_RE = re.compile(
    r"\b(?:linkedin\.com|github\.com|facebook\.com|instagram\.com|twitter\.com|"
    r"x\.com|youtube\.com|bit\.ly|t\.me)\S*",
    re.IGNORECASE,
)

# US, Indian, and generic international phone formats:
#   +country-code ...           (+1-202-555-0145, +91 98765 43210, +44 20 7946 0958)
#   (area) NN-NNNN              ((415) 555-0123)
#   NNN-NNN-NNNN                987-654-3210
#   NNNNN NNNNN                 (Indian mobile 98200 12345)
_PHONE_RE = re.compile(
    r"(?<![\d])("
    r"\+\d{1,3}(?:[\s.-]?\d+){2,8}"
    r"|\(\d{1,4}\)[\s.-]?\d{3,5}[\s.-]?\d{3,5}"
    r"|\d{3}[\s.-]?\d{3}[\s.-]?\d{4}"
    r"|\d{5}[\s.-]\d{5}"
    r")(?![\d])"
)

_ADDR_SUFFIX_WORDS = (
    "main", "street", "road", "avenue", "drive", "lane",
    "boulevard", "court", "colony", "nagar", "layout", "extension",
    "gali", "marg", "highway", "cross",
)
_ADDR_SUFFIX_ABBRS = ("st.", "rd.", "ave.", "dr.", "ln.", "blvd.", "ct.", "ext.", "hwy.")
_SUFFIX_PATTERN = (
    r"(?:main\s+|street|st\.?|road|rd\.?|avenue|ave\.?|drive|dr\.?|"
    r"lane|ln\.?|boulevard|blvd\.?|court|ct\.?|colony|nagar|layout|"
    r"extension|ext\.?|gali|marg|highway|hwy\.?)\b"
)
_STREET_RE = re.compile(
    r"\b\d{1,5}\s*[,.-]?\s+"
    r"(?=[A-Za-z0-9])"
    r"(?:[A-Za-z0-9'\-]+\s+)*?" + _SUFFIX_PATTERN,
    re.IGNORECASE,
)
_CITY_ST_ZIP_RE = re.compile(r"^[A-Za-z][\w .'-]{2,60},\s+[A-Za-z. ]+?\s+\d{5}(?:-\d{4})?$")
_PIN_RE = re.compile(r"\b[1-9]\d{5}\b")

_NAME_LINE_RE = re.compile(
    r"^[A-Z][A-Za-z'\-]*\.?(?:\s+[A-Z][A-Za-z'\-]*\.?)*$"
)
_NAME_STOPWORDS = {
    "cv", "curriculum", "vitae", "resume", "resumes", "objective", "summary",
    "profile", "contact", "phone", "email", "address", "location", "work",
    "experience", "education", "skills", "skill", "projects", "project", "about",
    "internship", "intern", "trainee", "position", "seeking", "available", "open",
    "looking", "engineer", "developer", "dev", "analyst", "scientist", "researcher",
    "consultant", "manager", "specialist", "associate", "architect", "executive",
    "leader", "lead", "head", "director", "owner", "founder", "president", "ceo",
    "cto", "coo", "vp", "officer", "designer", "design", "data", "software",
    "backend", "back-end", "frontend", "front-end", "full-stack", "full", "stack",
    "devops", "machine", "learning", "product", "program", "security", "teacher",
    "professor", "mentor", "coach", "marketing", "sales", "student", "graduate",
    "test", "qa", "quality", "principal", "staff", "senior", "junior", "tester",
    "mobile", "web", "cloud", "ai", "ml", "sap", "salesforce",
}
_CONTACT_HINTS = ("[email]", "[phone]", "[link]", "[address]")

_PLACEHOLDERS = re.compile(r"\[(email|phone|link|address|name)\]")


def _is_name_candidate(line: str) -> bool:
    if len(line) > 40:
        return False
    if not _NAME_LINE_RE.match(line):
        return False
    tokens = [t.rstrip(".") for t in line.split()]
    if not 1 <= len(tokens) <= 4:
        return False
    if any(t.lower() in _NAME_STOPWORDS for t in tokens):
        return False
    if len(tokens) == 1 and len(tokens[0]) < 5:
        return False
    return True


def _detect_name(lines: list[str]) -> str:
    """Find the candidate's name near the top of the resume (or before a contact line)."""
    candidates = [i for i, ln in enumerate(lines) if _is_name_candidate(ln.strip())]
    if not candidates:
        return ""
    for i in candidates:
        nxt = next((lines[j].strip() for j in range(i + 1, len(lines)) if lines[j].strip()), "")
        if any(h in nxt for h in _CONTACT_HINTS):
            return lines[i].strip()
    for i in candidates:
        if i == 0:
            return lines[i].strip()
    return ""


def _redact_address_line(line: str) -> str:
    stripped = line.strip()
    if _STREET_RE.search(line):
        return "[address]"
    if _CITY_ST_ZIP_RE.match(stripped):
        return "[address]"
    if _PIN_RE.search(line) and len(stripped) <= 80:
        return "[address]"
    return line


def sanitize_resume_text(text: str) -> str:
    """Redact contact PII (name, email, phone, URLs, addresses) from resume text."""
    if not text:
        return text

    out = _EMAIL_RE.sub("[email]", text)
    out = _PHONE_RE.sub("[phone]", out)
    out = _URL_RE.sub("[link]", out)
    out = _DOMAIN_LINK_RE.sub("[link]", out)

    lines = out.splitlines()
    lines = [_redact_address_line(ln) for ln in lines]

    if any(_PLACEHOLDERS.search(ln) for ln in lines[:8]):
        name = _detect_name(lines)
        if name:
            name_pat = re.compile(r"\b" + re.escape(" ".join(name.split())) + r"\b", re.IGNORECASE)
            lines = [name_pat.sub("[name]", ln) for ln in lines]

    result = "\n".join(lines)
    return result
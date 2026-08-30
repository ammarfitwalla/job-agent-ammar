import re

INTERN_INDICATORS = [
    "intern", "internship", "internship program", "summer intern",
]

ENTRY_INDICATORS = [
    "entry level", "entry-level", "fresher", "fresh graduate",
    "graduate trainee", "graduate program", "new grad", "new graduate",
    "junior", "trainee", "apprentice", "junior engineer",
    "junior developer", "associate", "associate trainee",
]

SENIOR_INDICATORS = [
    "senior", "lead", "head of", "principal", "staff",
    "director", "vp", "vice president", "chief", "manager",
    "head", "architect",
]

MID_LEVEL_INDICATORS = [
    r"\bii\b", r"\biii\b", r"\biv\b", r"\bsr\b", r"\bsnr\b",
    r"mid.level", r"experienced", r"level ii", r"level iii",
]


def level_from_job_level(job_level: str | None) -> str | None:
    """Map a board-provided seniority tag (e.g. LinkedIn's job_level)
    onto our experience_level vocabulary. Returns None for anything
    that isn't clearly entry-level, so senior/mid tags pass through.
    """
    if not isinstance(job_level, str):
        return None
    jl = job_level.strip().lower()
    if jl in ("internship", "student"):
        return "internship"
    if jl in ("entry level", "associate", "trainee"):
        return "entry_level"
    return None


def detect_experience_level(title: str, description: str | None = "") -> str | None:
    if not isinstance(title, str):
        title = ""
    if not isinstance(description, str):
        description = ""
    title_lower = title.lower()
    desc_lower = description.lower() if description else ""
    combined = f"{title_lower} {desc_lower}"

    for w in SENIOR_INDICATORS:
        if re.search(rf'\b{re.escape(w)}\b', title_lower):
            return None

    for pat in MID_LEVEL_INDICATORS:
        if re.search(pat, title_lower):
            return None

    for w in INTERN_INDICATORS:
        if w in title_lower:
            return "internship"

    for w in ENTRY_INDICATORS:
        if re.search(rf'\b{re.escape(w)}\b', title_lower):
            return "entry_level"

    # YOE check: find the first explicit YOE requirement
    found_yoe = None

    range_m = re.search(r'(\d+)\s*[-–to]+\s*\d+\s*(?:years?|yrs?)', desc_lower)
    if range_m:
        found_yoe = int(range_m.group(1))

    if found_yoe is None:
        m = re.search(r'(?:at least|minimum|min)\s*(\d+)\s*(?:years?|yrs?)', desc_lower)
        if m:
            found_yoe = int(m.group(1))

    if found_yoe is None:
        for n in range(1, 16):
            if re.search(rf"{n}\s*\+?\s*(?:years?|yrs?|yr\.)'?\s*(?:of\s+)?(?:[\w-]+\s+){{0,3}}(?:experience|exp|xp)", desc_lower):
                found_yoe = n
                break

    if found_yoe is not None:
        return None if found_yoe >= 3 else "entry_level"

    for w in INTERN_INDICATORS:
        if w in combined:
            if any(kw in desc_lower for kw in ["no experience", "entry level", "fresh graduate", "training provided", "mentorship"]):
                return "internship"

    for w in ENTRY_INDICATORS:
        if re.search(rf'\b{re.escape(w)}\b', desc_lower):
            return "entry_level"

    return None


# ── Years-of-experience buckets ──────────────────────────────────────────
# Granular YOE classification used by the jobs listing filter. Jobs are placed
# into a bucket from the numeric requirement (minimum) found in the description;
# when no number is given the title / board-provided seniority tag is used.
YOE_BUCKET_ORDER = ["0-2", "2-4", "4-7", "7-10", "10+"]
YOE_NOT_SPECIFIED = "not_specified"

_YOE_RANGE = re.compile(r'(\d{1,2})\s*(?:-|–|—|to)\s*\d{1,2}\s*(?:years?|yrs?)\b')
_YOE_AT_LEAST = re.compile(r'(?:at\s*least|minimum\s*of?|min)\s*(\d{1,2})\s*(?:years?|yrs?)\b')
_YOE_PLUS_EXP = re.compile(
    r'(\d{1,2})\s*\+?\s*(?:years?|yrs?)\s*(?:of\s*)?'
    r'(?:relevant|related|professional|practical|proven|work)?\s*(?:experience|exp)\b')
_YOE_NUM_BARE = re.compile(r'\b(\d{1,2})\s*\+?\s*(?:years?|yrs?)\b')
_YOE_CTX_HINT = re.compile(r'(?:experience|exp\b|qualif|require|minimum|at least|relevan|of work)')
_YOE_CURRENCY = re.compile(r'[$€£]\s*\d[\d,]*(?:k|K)?')

# Title/description seniority fallback, most-senior first (so "Senior Manager"
# lands in the manager bucket, not the senior one).
_SENIOR_FALLBACK = [
    ("10+", ("director", "vp", "vice president", "head of", "chief", "executive")),
    ("7-10", ("principal", "staff", "architect", "manager", "lead", "tech lead")),
    ("4-7", ("senior", "snr", "sr")),
    ("2-4", ("mid-level", "mid level", "level ii")),
    ("0-2", ("intern", "internship", "trainee", "apprentice", "entry level", "entry-level",
             "fresher", "fresh graduate", "new grad", "junior", "graduate program",
             "graduate trainee")),
]

_JOB_LEVEL_FALLBACK = {
    "internship": "0-2", "student": "0-2", "entry level": "0-2",
    "associate": "0-2", "trainee": "0-2",
    "mid-senior level": "4-7", "senior": "4-7",
    "director": "10+", "executive": "10+",
}


def _bucket_for_min(min_yoe: int) -> str:
    if min_yoe <= 1:
        return "0-2"
    if min_yoe <= 3:
        return "2-4"
    if min_yoe <= 6:
        return "4-7"
    if min_yoe <= 10:
        return "7-10"
    return "10+"


def _extract_min_yoe(description: str | None) -> int | None:
    """Return the minimum years-of-experience a job asks for, or None."""
    if not description:
        return None
    desc = description.lower()
    desc = _YOE_CURRENCY.sub(" ", desc)
    for pat in (_YOE_AT_LEAST, _YOE_RANGE, _YOE_PLUS_EXP):
        m = pat.search(desc)
        if m:
            return int(m.group(1))
    for m in _YOE_NUM_BARE.finditer(desc):
        n = int(m.group(1))
        if n > 15:
            continue
        tail = desc[m.end():m.end() + 50]
        head = desc[max(0, m.start() - 25):m.start()]
        if _YOE_CTX_HINT.search(tail) or _YOE_CTX_HINT.search(head):
            return n
    return None


def _senior_word_fallback(text: str) -> str | None:
    for bucket, words in _SENIOR_FALLBACK:
        for w in words:
            if re.search(rf'\b{re.escape(w)}\b', text):
                return bucket
    return None


def yoe_bucket_from_job(title: str, description: str | None = "", job_level: str | None = "") -> str:
    """Classify a job into a years-of-experience bucket.

    Returns one of YOE_BUCKET_ORDER (e.g. "4-7") or YOE_NOT_SPECIFIED.
    Numeric requirements always win; title words beat the board tag; the
    description is used as a last resort before "not_specified".
    """
    if description:
        min_yoe = _extract_min_yoe(description)
        if min_yoe is not None:
            return _bucket_for_min(min_yoe)

    title_lower = (title or "").lower()
    bucket = _senior_word_fallback(title_lower)
    if bucket:
        return bucket

    if isinstance(job_level, str):
        jl = job_level.strip().lower()
        if jl in _JOB_LEVEL_FALLBACK:
            return _JOB_LEVEL_FALLBACK[jl]

    if description:
        bucket = _senior_word_fallback(description.lower())
        if bucket:
            return bucket

    return YOE_NOT_SPECIFIED

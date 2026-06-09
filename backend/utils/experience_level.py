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


def detect_experience_level(title: str, description: str = "") -> str | None:
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

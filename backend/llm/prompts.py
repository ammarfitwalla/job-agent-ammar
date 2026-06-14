# Relevance + Cover Letter prompts
import re
from match_engine import resume_data as _resume_data
from utils.logger import log


SKILL_SECTIONS = [
    "requirement", "qualification", "qualifications", "skill", "skills",
    "responsibility", "responsibilities", "requirements",
    "what you'?ll do", "you will", "about the role",
    "key responsibility", "key responsibilities", "must have", "nice to have",
    "preferred", "ideal candidate", "we are looking for",
    "what we look for", "your profile", "about you",
    "join our", "work on", "you will", "you'll",
    "the role", "this role", "as a ",
    "years? of experience", "years? exp", "years? of exp",
    "experience required", "qualifications", "education",
]


def _extract_relevant(text: str, max_chars: int = 0) -> str:
    """Smart truncation — keeps paragraphs with skill/requirement keywords."""
    if max_chars <= 0 or len(text) <= max_chars:
        return text

    paragraphs = re.split(r'\n\s*\n', text)
    if len(paragraphs) <= 1:
        return text[:max_chars]

    scored = []
    for p in paragraphs:
        if not p.strip():
            continue
        p_lower = p.lower()
        score = sum(2 for kw in SKILL_SECTIONS if re.search(kw, p_lower))
        scored.append((score, p))

    scored.sort(key=lambda x: x[0], reverse=True)

    result = scored[0][1] + "\n\n"
    kept = 1
    for score, p in scored[1:]:
        if len(result) + len(p) + 2 <= max_chars:
            result += p + "\n\n"
            kept += 1

    return result.strip()


def _extract_resume(resume: str) -> str:
    return resume


# ================
# 1️⃣ RELEVANCE SCORING PROMPT
# ================
def relevance_prompt(job_title: str, jd: str, tags: list[str] = None, resume: str = None):
    tags_section = ""
    if tags:
        tags_section = f"Job Tags: {', '.join(tags)}\n"

    resume_text = _extract_resume(resume if resume else _resume_data.RESUME_TEXT)
    jd_text = _extract_relevant(jd, max_chars=3000)

    return f"""
You are an expert hiring manager. Compare the job vs the candidate's resume.

Resume:
{resume_text}

Job Title: {job_title}
{tags_section}Job Description:
{jd_text}

Scoring Rules (0–100):
- Score based on how well skills, experience, and domain match the resume
- +40 if the core role/domain matches the candidate's background
- +20 if required tools, technologies, or methodologies match
- +15 if the candidate has relevant experience level
- +10 if secondary skills or nice-to-haves match
- -20 if the role is in a different domain or seniority mismatch
- -40 if the role is completely unrelated to the candidate's background

Respond ONLY in JSON:
{{
  "score": <0-100 integer>,
  "reason": "<one-line explanation>",
  "is_relevant": true/false,
  "required_years": <integer 0-15>
}}

without using ```
"""


# ================
# 1️⃣B INTERNSHIP RELEVANCE SCORING PROMPT
# ================
def internship_relevance_prompt(job_title: str, jd: str, tags: list[str] = None, resume: str = None):
    tags_section = ""
    if tags:
        tags_section = f"Job Tags: {', '.join(tags)}\n"

    resume_text = _extract_resume(resume if resume else _resume_data.RESUME_TEXT)
    jd_text = _extract_relevant(jd, max_chars=3000)

    return f"""
You are a strict hiring manager. Compare the job to the candidate's resume.

Resume:
{resume_text}

Job Title: {job_title}
{tags_section}Job Description:
{jd_text}

Instructions:
1. FIRST, extract 3-5 key skills/tools/domains explicitly mentioned in the job description.
2. THEN, check which of those appear in the resume.
3. Score based ONLY on how many JD skills match the resume:
   - 0-1 matching: score 10-30, is_relevant=false
   - 2-3 matching: score 40-60, is_relevant=true
   - 4+ matching: score 70-100, is_relevant=true
4. Your reason MUST quote specific phrases from the JD. If no JD skills match the resume, the score is 15 and is_relevant=false.
5. Do NOT list resume skills that are absent from the JD.

Examples:
- JD says "Salesforce, cold calling, CRM". Resume has Salesforce, lead gen. → 1 match → score 25, false
- JD says "AutoCAD, Revit, steel design". Resume has AutoCAD, structural analysis. → 1 match → score 25, false
- JD says "Docker, AWS, Python, Kubernetes". Resume has Docker, AWS, Python. → 3 matches → score 55, true
- JD says "electrical engineering". Resume has sales skills. → 0 matches → score 15, false

Respond ONLY in JSON:
{{
  "score": <0-100 integer>,
  "reason": "<one-line explanation>",
  "is_relevant": true/false,
  "matched_skills": ["skill1", "skill2"],
  "required_years": <integer 0-15>
}}

without using ```
"""


# ================
# 1️⃣C BATCH RELEVANCE SCORING PROMPT
# ================
def batch_relevance_prompt(
    jobs: list[tuple[str, str, list[str]]],
    resume: str = None,
    internship_mode: bool = False,
) -> str:
    resume_text = _extract_resume(resume if resume else _resume_data.RESUME_TEXT)

    if internship_mode:
        instructions = """
For each job, extract 3-5 key skills/tools/domains from its JD ONLY, then check how many
appear in the resume. Score based ONLY on JD-to-resume skill overlap:
  - 0-1 matching → score 10-30, is_relevant=false
  - 2-3 matching → score 40-60, is_relevant=true
  - 4+ matching  → score 70-100, is_relevant=true
If required_years >= 3, set is_relevant=false.
Do NOT hallucinate or invent skills. Every skill listed MUST appear verbatim in the JD text.
Do NOT list resume skills absent from the JD.
"""
    else:
        instructions = """
For each job, score 0–100 based on how well skills, experience, and domain
match the resume:
  - +40 if the core role/domain matches
  - +20 if required tools / technologies / methodologies match
  - +15 if the candidate has relevant experience level
  - +10 if secondary skills or nice-to-haves match
  - -20 if domain or seniority mismatch
  - -40 if completely unrelated
"""

    job_blocks = []
    for i, (title, jd, tags) in enumerate(jobs, 1):
        tags_str = f"Job Tags: {', '.join(tags)}\n" if tags else ""
        jd_text = _extract_relevant(jd, max_chars=3000)
        job_blocks.append(f"--- JOB {i} ---\nTitle: {title}\n{tags_str}Description:\n{jd_text}")

    jobs_text = "\n\n".join(job_blocks)

    return f"""
You are an expert hiring manager. Compare each job below against the candidate's resume.

Resume:
{resume_text}

{instructions}

{jobs_text}

Respond ONLY with a JSON array, one object per job in the same order:
[
  {{
    "score": <0-100>,
    "reason": "<one-line explanation>",
    "is_relevant": true/false,
    "matched_skills": ["skill1", "skill2"],
    "missing_skills": ["skill1"],
    "required_years": <0-15>
  }}
]

without using ``` or any extra text.
"""


# ================
# 2️⃣ COVER LETTER PROMPT
# ================
def cover_letter_prompt(company: str, role: str, jd: str):
    return f"""
Write a concise 120–180 word cover letter.

Candidate Resume:
{_resume_data.RESUME_TEXT}

Job Role: {role}
Company: {company}
Job Description:
{jd}

Guidelines:
- Be confident but not arrogant.
- Highlight AI/ML, backend, cloud skills.
- Mention building ML systems & APIs.
- Include 1 line showing enthusiasm for the company.
- No buzzwords without meaning.

Respond with ONLY the cover letter text.
"""


# ================
# 3️⃣ GENERIC CLEANUP PROMPT (optional)
# ================
def clean_text_prompt(text: str):
    return f"Clean this text and remove garbage formatting:\n\n{text}"

# Relevance + Cover Letter prompts
from match_engine import resume_data as _resume_data


# ================
# 1️⃣ RELEVANCE SCORING PROMPT
# ================
def relevance_prompt(job_title: str, jd: str, tags: list[str] = None):
    tags_section = ""
    if tags:
        tags_section = f"Job Tags: {', '.join(tags)}\n"

    return f"""
You are an expert hiring manager. Compare the job vs the candidate's resume.

Resume:
{_resume_data.RESUME_TEXT}

Job Title: {job_title}
{tags_section}Job Description:
{jd}

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
  "is_relevant": true/false
}}

without using ```
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

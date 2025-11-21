# Relevance + Cover Letter prompts
from match_engine.resume_data import RESUME_TEXT


# ================
# 1️⃣ RELEVANCE SCORING PROMPT
# ================
def relevance_prompt(job_title: str, jd: str):
    return f"""
You are an expert AI/ML hiring manager.

Your job:
Rate how relevant this job is to the candidate's resume below.

Resume:
{RESUME_TEXT}

Job Title: {job_title}
Job Description:
{jd}

Scoring Rules (0–100):
- +40 if it's directly AI/ML/Data Science
- +20 if requires Python, ML frameworks (TF, PyTorch)
- +15 if backend Python/API experience is useful
- +10 if cloud (AWS/GCP) matches resume
- -20 if it's not technical
- -40 if it's sales, HR, marketing or unrelated

Respond ONLY in JSON:
{{
  "score": <0-100 integer>,
  "reason": "<one-line explanation>",
  "is_relevant": true/false
}}
"""


# ================
# 2️⃣ COVER LETTER PROMPT
# ================
def cover_letter_prompt(company: str, role: str, jd: str):
    return f"""
Write a concise 120–180 word cover letter.

Candidate Resume:
{RESUME_TEXT}

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

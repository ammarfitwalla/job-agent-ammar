from fastapi import APIRouter
from pydantic import BaseModel
from utils.json_parser import extract_json

router = APIRouter(prefix="/resume", tags=["resume"])


class ResumeKeywordsRequest(BaseModel):
    resume_text: str


class ResumeKeywordsResponse(BaseModel):
    keywords: list[dict]


EXTRACT_PROMPT = """Extract the top 20 most relevant keywords from this resume. Only include skills, tools, software, concepts, certifications, and domain expertise that explicitly appear in the resume text.

Rules:
- ONLY extract keywords that are literally written in the resume
- Do NOT guess, infer, or add related terms
- Return ONLY a JSON array of lowercase strings
- No markdown, no explanation
- Max 20 items

Resume:
{resume}"""


@router.post("/keywords", response_model=ResumeKeywordsResponse)
async def extract_keywords(req: ResumeKeywordsRequest):
    try:
        from llm.llm_client import LLMClient
        prompt = EXTRACT_PROMPT.format(resume=req.resume_text)
        response = LLMClient.chat(prompt, max_tokens=500)
        print(f"[KEYWORDS] LLM response received ({len(response)} chars)")

        parsed = extract_json(response)
        if isinstance(parsed, list):
            words = parsed[:30]
        else:
            print(f"[KEYWORDS] LLM parse failed, returning empty")
            words = []
    except Exception as e:
        print(f"[KEYWORDS] Exception: {e}, returning empty")
        words = []

    keywords = [{"word": w, "suggested": True, "selected": True} for w in words]
    return ResumeKeywordsResponse(keywords=keywords)

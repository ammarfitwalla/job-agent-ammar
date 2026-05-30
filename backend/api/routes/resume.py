from fastapi import APIRouter
from pydantic import BaseModel
import re
from collections import Counter
from utils.json_parser import extract_json

router = APIRouter(prefix="/resume", tags=["resume"])


class ResumeKeywordsRequest(BaseModel):
    resume_text: str


class ResumeKeywordsResponse(BaseModel):
    keywords: list[dict]


FALLBACK_KEYWORDS = [
    "python", "tensorflow", "pytorch", "machine learning", "data science", "ai", "llm",
    "aws", "gcp", "azure", "docker", "kubernetes", "sql", "postgresql", "react",
    "project management", "data analysis", "content writing", "sales",
    "customer success", "marketing", "seo", "financial analysis", "accounting",
    "recruiting", "hr", "operations", "supply chain", "logistics",
]


def _fallback_extract(text: str) -> list[str]:
    text = text.lower()
    found = set()
    for kw in FALLBACK_KEYWORDS:
        if kw in text:
            found.add(kw)
    words = re.findall(r"\b[a-z]{3,}\b", text)
    freq = Counter(words)
    common = {"the","and","for","with","from","this","that","have","been",
              "were","was","are","has","had","not","but","all","can","each",
              "which","their","will","about","into","than","what","when","also",
              "how","use","used","using","experience","work","team","project",
              "data","management","development","design","learning"}
    for word, _ in freq.most_common(20):
        if word not in common and word not in found:
            found.add(word)
    return sorted(found)[:30]


EXTRACT_PROMPT = """
You are a resume keyword extractor. Given a resume, extract the top 20 most relevant keywords: 
skills, tools, technologies, frameworks, concepts, and domain-specific expertise that appear in the resume.

Return ONLY a JSON array of unique lowercase strings, no explanation, no markdown.
Example: ["python", "project management", "sales", "aws", "data analysis", "content writing", "react", "financial modeling"]
Maximum 20 items.

Resume:
{resume}
"""


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
            print(f"[KEYWORDS] Extracted {len(words)} keywords via LLM: {words}")
        else:
            print(f"[KEYWORDS] LLM parse failed, using fallback")
            words = _fallback_extract(req.resume_text)
            print(f"[KEYWORDS] Extracted {len(words)} keywords via fallback: {words}")
    except Exception as e:
        print(f"[KEYWORDS] Exception: {e}, using fallback")
        words = _fallback_extract(req.resume_text)
        print(f"[KEYWORDS] Extracted {len(words)} keywords via fallback: {words}")

    keywords = [{"word": w, "suggested": True, "selected": True} for w in words]
    return ResumeKeywordsResponse(keywords=keywords)

# AI + keyword scoring engine
from llm.ollama_client import OllamaLLM
from llm.prompts import relevance_prompt
from config import KEYWORDS_INCLUDE, KEYWORDS_EXCLUDE
from utils.logger import log

def keyword_score(job_title: str, job_desc: str) -> int:
    """Simple keyword-based scoring"""
    score = 0
    combined_text = f"{job_title} {job_desc}".lower()

    for kw in KEYWORDS_INCLUDE:
        if kw.lower() in combined_text:
            score += 10

    for kw in KEYWORDS_EXCLUDE:
        if kw.lower() in combined_text:
            score -= 20

    return score


def ai_relevance_score(job_title: str, job_desc: str) -> dict:
    """
    Ask local LLM (Ollama) to score relevance.
    Returns dict: {'score': int, 'reason': str, 'is_relevant': bool}
    """
    prompt = relevance_prompt(job_title, job_desc)
    response = OllamaLLM.chat(prompt)

    try:
        import json
        parsed = json.loads(response)
        return parsed
    except Exception as e:
        log(f"[AI PARSE ERROR] {e} | response: {response}")
        return {"score": 0, "reason": "LLM parsing failed", "is_relevant": False}


def filter_jobs(jobs: list, min_score: int = 50) -> list:
    """
    Filter a list of jobs, return only relevant ones.
    Combines AI score + keyword score
    """
    filtered = []

    for job in jobs:
        kw_score = keyword_score(job["title"], job["description"])
        ai_result = ai_relevance_score(job["title"], job["description"])
        total_score = kw_score + ai_result.get("score", 0)

        if total_score >= min_score and ai_result.get("is_relevant", False):
            job["ai_score"] = ai_result.get("score", 0)
            job["keyword_score"] = kw_score
            job["total_score"] = total_score
            job["reason"] = ai_result.get("reason", "")
            filtered.append(job)

    log(f"[MATCH ENGINE] {len(filtered)} relevant jobs found out of {len(jobs)}")
    return filtered

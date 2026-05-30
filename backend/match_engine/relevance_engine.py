# AI + keyword scoring engine
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from llm.llm_client import LLMClient
from llm.prompts import relevance_prompt
import config
from utils.logger import log
from utils.json_parser import extract_json

def keyword_score(job_title: str, job_desc: str, keywords: Optional[list[str]] = None) -> int:
    score = 0
    combined_text = f"{job_title} {job_desc}".lower()

    kw_list = keywords if keywords else config.KEYWORDS_INCLUDE
    for kw in kw_list:
        if kw.lower() in combined_text:
            score += 10

    for kw in config.KEYWORDS_EXCLUDE:
        if kw.lower() in combined_text:
            score -= 20

    return score


def _score_one(args):
    """Score a single job and return it with AI fields if relevant."""
    job, min_score, keywords = args
    kw_score = keyword_score(job["title"], job["description"], keywords)

    # Skip LLM if no keywords match — job is almost certainly irrelevant
    if kw_score == 0:
        print(f"[SKIP] {job['title']}: kw=0, no LLM call needed")
        return None

    prompt = relevance_prompt(job["title"], job["description"])
    response = LLMClient.chat(prompt)
    print(f"[AI] {job['title']} -> {response[:120]}...")

    ai_result = extract_json(response)
    if not isinstance(ai_result, dict):
        ai_result = {"score": 0, "is_relevant": False}

    total_score = kw_score + ai_result.get("score", 0)
    print(f"[SCORE] {job['title']}: kw={kw_score} ai={ai_result.get('score')} total={total_score} relevant={ai_result.get('is_relevant')}")

    if total_score >= min_score and ai_result.get("is_relevant", False):
        job["ai_score"] = ai_result.get("score", 0)
        job["keyword_score"] = kw_score
        job["total_score"] = total_score
        job["reason"] = ai_result.get("reason", "")
        return job
    return None


def filter_jobs(jobs: list, min_score: int = 50, keywords: Optional[list[str]] = None) -> list:
    log(f"[MATCH ENGINE] Scoring {len(jobs)} jobs...")

    # Compute keyword scores first (fast, no LLM)
    for job in jobs:
        job["_kw_score"] = keyword_score(job["title"], job["description"], keywords)

    # Sort by keyword score desc, take top 5 for LLM
    jobs_sorted = sorted(jobs, key=lambda j: j["_kw_score"], reverse=True)
    llm_candidates = [j for j in jobs_sorted if j["_kw_score"] > 0][:5]

    log(f"[MATCH ENGINE] {len(llm_candidates)}/{len(jobs)} jobs sent to LLM (top 5 by keyword match)")

    filtered = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(_score_one, (job, min_score, keywords)) for job in llm_candidates]
        for future in as_completed(futures):
            try:
                result = future.result(timeout=60)
                if result is not None:
                    filtered.append(result)
            except Exception as e:
                log(f"[MATCH ENGINE] Job scoring error: {e}")

    # Clean up temp key
    for job in jobs:
        job.pop("_kw_score", None)

    log(f"[MATCH ENGINE] {len(filtered)} relevant jobs out of {len(jobs)}")
    return filtered

# AI + keyword scoring engine
import copy
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from llm.llm_client import LLMClient
from llm.prompts import relevance_prompt
import config
from utils.logger import log
from utils.json_parser import extract_json


def keyword_score(
    job_title: str,
    job_desc: str,
    job_tags: Optional[list] = None,
    keywords: Optional[list] = None,
) -> int:
    combined = f"{job_title} {job_desc}".lower()
    if job_tags:
        combined += " " + " ".join(job_tags).lower()

    kw_list = keywords if keywords else config.KEYWORDS_INCLUDE
    return sum(10 for kw in kw_list if kw.lower() in combined)


def _score_one(
    job: dict,
    min_score: int,
    keywords: Optional[list],
    resume: Optional[str],
    llm_weight: float,
    kw_weight: float,
) -> Optional[dict]:
    kw_score = keyword_score(job["title"], job["description"], job.get("tags"), keywords)

    prompt = relevance_prompt(job["title"], job["description"], job.get("tags"), resume=resume)
    response = LLMClient.chat(prompt)

    ai_result = extract_json(response)
    if not isinstance(ai_result, dict):
        log(f"[WARN] Unparseable AI response for: {job['title']}")
        return None

    ai_score = int(ai_result.get("score", 0))
    kw_norm = min(kw_score, 100)
    total_score = round(ai_score * llm_weight + kw_norm * kw_weight)

    log(f"[SCORE] {job['title']}: kw={kw_score}(norm={kw_norm}) ai={ai_score} "
        f"total={total_score} relevant={ai_result.get('is_relevant')}")

    if total_score < min_score or not ai_result.get("is_relevant", False):
        return None

    return {
        **copy.copy(job),
        "ai_score": ai_score,
        "keyword_score": kw_score,
        "total_score": total_score,
        "reason": ai_result.get("reason", ""),
        "matched_skills": ai_result.get("matched_skills", []),
        "missing_skills": ai_result.get("missing_skills", []),
    }


def filter_jobs(
    jobs: list,
    min_score: int = 50,
    keywords: Optional[list] = None,
    resume: Optional[str] = None,
    llm_candidate_limit: int = 10,
    llm_weight: float = 0.7,
    kw_weight: float = 0.3,
    max_workers: int = 3,
    progress_callback=None,
) -> list:
    if not jobs:
        return []

    log(f"[MATCH ENGINE] {len(jobs)} jobs received")

    kw_scored = [
        (job, keyword_score(job["title"], job["description"], job.get("tags"), keywords))
        for job in jobs
    ]

    candidates = sorted(kw_scored, key=lambda x: x[1], reverse=True)[:llm_candidate_limit]

    log(f"[MATCH ENGINE] {len(candidates)}/{len(jobs)} sent to LLM (limit={llm_candidate_limit})")

    filtered = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(_score_one, job, min_score, keywords, resume, llm_weight, kw_weight): job["title"]
            for job, _ in candidates
        }
        for future in as_completed(futures):
            title = futures[future]
            try:
                result = future.result(timeout=60)
                if result is not None:
                    filtered.append(result)
                    if progress_callback:
                        progress_callback(result)
            except Exception as e:
                log(f"[MATCH ENGINE] Error scoring '{title}': {e}")

    filtered.sort(key=lambda j: j["total_score"], reverse=True)
    log(f"[MATCH ENGINE] {len(filtered)} relevant jobs returned")
    return filtered

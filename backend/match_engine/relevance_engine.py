# AI + keyword scoring engine
import copy
import json
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from llm.llm_client import LLMClient
from llm.prompts import relevance_prompt, internship_relevance_prompt, batch_relevance_prompt
from llm.providers import GroqProvider
import config
from utils.logger import log
from utils.json_parser import extract_json

BATCH_SIZE_RATIO = {True: 3, False: 5}  # internship vs normal
_groq_provider = GroqProvider()


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


def _apply_scoring(
    job: dict,
    ai_result: dict,
    min_score: int,
    keywords: Optional[list],
    llm_weight: float,
    kw_weight: float,
    internship_mode: bool,
) -> Optional[dict]:
    """Apply parsed AI result and keyword score to a single job."""
    kw_score = keyword_score(job["title"], job["description"], job.get("tags"), keywords)

    ai_score = int(ai_result.get("score", 0))
    ai_relevant = ai_result.get("is_relevant", False)
    matched = ai_result.get("matched_skills", []) or []
    required_years = ai_result.get("required_years")

    if internship_mode and required_years is not None:
        try:
            if int(required_years) >= 3:
                log(f"[YOE-LLM] '{job['title']}': required_years={required_years} — rejecting")
                return None
        except (ValueError, TypeError):
            pass

    jd_lower = (job.get("description") or "").lower()
    title_lower = (job.get("title") or "").lower()
    verified = [s for s in matched if s.lower() in jd_lower or s.lower() in title_lower]
    hallucinated = len(matched) - len(verified)

    if internship_mode and len(verified) == 0 and len(matched) > 0:
        ai_score = 20
        ai_relevant = False

    kw_norm = min(kw_score, 100)
    total_score = round(ai_score * llm_weight + kw_norm * kw_weight)

    if total_score < min_score or not ai_relevant:
        return None

    return {
        **copy.copy(job),
        "ai_score": ai_score,
        "keyword_score": kw_score,
        "total_score": total_score,
        "reason": ai_result.get("reason", ""),
        "matched_skills": verified,
        "missing_skills": ai_result.get("missing_skills", []),
    }


def _score_one(
    job: dict,
    min_score: int,
    keywords: Optional[list],
    resume: Optional[str],
    llm_weight: float,
    kw_weight: float,
    internship_mode: bool = False,
) -> Optional[dict]:
    prompt = (internship_relevance_prompt if internship_mode else relevance_prompt)(
        job["title"], job["description"], job.get("tags"), resume=resume)
    response = (_groq_provider.chat if internship_mode else LLMClient.chat)(prompt)

    ai_result = extract_json(response)
    if not isinstance(ai_result, dict):
        log(f"[WARN] Unparseable AI response for: {job['title']}")
        return None

    return _apply_scoring(job, ai_result, min_score, keywords, llm_weight, kw_weight, internship_mode)


def _score_batch(
    batch_jobs: list[dict],
    min_score: int,
    keywords: Optional[list],
    resume: Optional[str],
    llm_weight: float,
    kw_weight: float,
    internship_mode: bool,
) -> list[dict]:
    """Score a batch of jobs (up to BATCH_SIZE) in one LLM call."""
    prompt = batch_relevance_prompt(
        [(j["title"], j["description"], j.get("tags")) for j in batch_jobs],
        resume=resume,
        internship_mode=internship_mode,
    )
    response = _groq_provider.chat(prompt, max_tokens=3000) if internship_mode else LLMClient.batch_chat(prompt)

    parsed = extract_json(response)
    if not isinstance(parsed, list):
        log(f"[BATCH WARN] Response is not a list — falling back to per-job scoring")
        results = []
        for job in batch_jobs:
            r = _score_one(job, min_score, keywords, resume, llm_weight, kw_weight, internship_mode)
            if r:
                results.append(r)
        return results

    results = []
    for job, ai_result in zip(batch_jobs, parsed):
        if not isinstance(ai_result, dict):
            log(f"[BATCH WARN] Invalid entry for '{job['title']}' — skipping")
            continue
        r = _apply_scoring(job, ai_result, min_score, keywords, llm_weight, kw_weight, internship_mode)
        if r:
            results.append(r)

    # If all jobs in batch failed but LLM returned something, fall back
    if not results and parsed:
        log(f"[BATCH WARN] All batch results rejected (internship={internship_mode}) — retrying individually")
        for job in batch_jobs:
            r = _score_one(job, min_score, keywords, resume, llm_weight, kw_weight, internship_mode)
            if r:
                results.append(r)

    return results


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
    internship_mode: bool = False,
) -> list:
    if not jobs:
        return []

    log(f"[MATCH ENGINE] {len(jobs)} jobs received")

    limit = llm_candidate_limit * 2 if internship_mode else llm_candidate_limit

    kw_scored = [
        (job, keyword_score(job["title"], job["description"], job.get("tags"), keywords))
        for job in jobs
    ]

    candidates = sorted(kw_scored, key=lambda x: x[1], reverse=True)[:limit]

    batch_size = BATCH_SIZE_RATIO[internship_mode]

    log(f"[MATCH ENGINE] {len(candidates)}/{len(jobs)} sent to LLM (limit={llm_candidate_limit}, batch_size={batch_size})")

    # Group into batches
    candidate_jobs = [job for job, _ in candidates]
    batches = [candidate_jobs[i:i + batch_size] for i in range(0, len(candidate_jobs), batch_size)]

    log(f"[MATCH ENGINE] {len(batches)} batch(es) of up to {batch_size}")

    filtered = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(
                _score_batch, batch, min_score, keywords, resume, llm_weight, kw_weight, internship_mode
            ): f"batch of {len(batch)}"
            for batch in batches
        }
        for future in as_completed(futures):
            label = futures[future]
            try:
                batch_results = future.result(timeout=90)
                for r in batch_results:
                    filtered.append(r)
                    if progress_callback:
                        progress_callback(r)
            except Exception as e:
                log(f"[MATCH ENGINE] Error scoring {label}: {e}")

    filtered.sort(key=lambda j: j["total_score"], reverse=True)
    log(f"[MATCH ENGINE] {len(filtered)} relevant jobs returned")
    return filtered

# AI + keyword scoring engine
import copy
import json
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from llm.llm_client import LLMClient
from llm.prompts import relevance_prompt, internship_relevance_prompt, batch_relevance_prompt
from llm.providers import CerebrasProvider
from config import INTERNSHIP_CEREBRAS_API_KEY, INTERNSHIP_CEREBRAS_MODEL, INTERNSHIP_CEREBRAS_RATE, CEREBRAS_API_URL, KEYWORDS_INCLUDE
from utils.logger import log
from utils.json_parser import extract_json

BATCH_SIZE_RATIO = {True: 2, False: 5}  # internship vs normal
_internship_provider = CerebrasProvider(
    api_key=INTERNSHIP_CEREBRAS_API_KEY,
    model=INTERNSHIP_CEREBRAS_MODEL,
    base_url=CEREBRAS_API_URL,
    rate_limit=INTERNSHIP_CEREBRAS_RATE,
)


def keyword_score(
    job_title: str,
    job_desc: str,
    job_tags: Optional[list] = None,
    keywords: Optional[list] = None,
) -> int:
    combined = f"{job_title} {job_desc}".lower()
    if job_tags:
        combined += " " + " ".join(job_tags).lower()

    kw_list = keywords if keywords else KEYWORDS_INCLUDE
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
    print(f"[DBG RE] _apply_scoring entry: job='{job['title']}', min_score={min_score}, internship={internship_mode}")
    kw_score = keyword_score(job["title"], job["description"], job.get("tags"), keywords)
    # print(f"[DBG RE] kw_score={kw_score}")

    ai_score = int(ai_result.get("score", 0))
    ai_relevant = ai_result.get("is_relevant", False)
    matched = ai_result.get("matched_skills", []) or []
    required_years = ai_result.get("required_years")
    print(f"[DBG RE]   ai_score={ai_score} relevant={ai_relevant} matched={matched} yrs={required_years} kw={kw_score}")

    if internship_mode and required_years is not None:
        try:
            if int(required_years) >= 3:
                # print(f"[DBG RE] YOE>=3 REJECT ('{job['title']}')")
                log(f"[YOE-LLM] '{job['title']}': required_years={required_years} — rejecting")
                return None
        except (ValueError, TypeError):
            pass

    jd_lower = (job.get("description") or "").lower()
    title_lower = (job.get("title") or "").lower()
    verified = [s for s in matched if s.lower() in jd_lower or s.lower() in title_lower]
    hallucinated = len(matched) - len(verified)
    # print(f"[DBG RE] verified={len(verified)}/{len(matched)} skills in JD, hallucinated={hallucinated}")

    if internship_mode and len(verified) == 0 and len(matched) > 0:
        # print(f"[DBG RE] internship zero-match override — score=20, relevant=False")
        ai_score = 20
        ai_relevant = False

    kw_norm = min(kw_score, 100)
    total_score = round(ai_score * llm_weight + kw_norm * kw_weight)
    # print(f"[DBG RE] total_score={total_score} = ai({ai_score})*{llm_weight} + kw({kw_norm})*{kw_weight}, threshold={min_score}, ai_relevant={ai_relevant}")

    if total_score < min_score or not ai_relevant:
        # print(f"[DBG RE] REJECTED (score={total_score} < {min_score} or relevant={ai_relevant})")
        return None

    # print(f"[DBG RE] PASS — total_score={total_score}")
    return {
        **copy.copy(job),
        "ai_score": ai_score,
        "keyword_score": kw_norm,
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
    sid: str = None,
    cancel_check: Optional[callable] = None,
) -> Optional[dict]:
    # print(f"[DBG RE] _score_one entry: job='{job['title']}', internship={internship_mode}")
    if cancel_check and cancel_check():
        return None
    prompt = (internship_relevance_prompt if internship_mode else relevance_prompt)(
        job["title"], job["description"], job.get("tags"), resume=resume)
    # print(f"[DBG RE] _score_one: prompt built, len={len(prompt)}, mode={'internship' if internship_mode else 'normal'}")
    response = ""
    if internship_mode:
        response = _internship_provider.chat(prompt, cancel_check=cancel_check)
        # print(f"[DBG RE] _score_one: internship_provider.chat() returned {'SUCCESS' if response else 'EMPTY'} (len={len(response)})")
    if not response and not (cancel_check and cancel_check()):
        response = LLMClient.chat(prompt, cancel_check=cancel_check)
        # print(f"[DBG RE] _score_one: LLMClient.chat() returned {'SUCCESS' if response else 'EMPTY'} (len={len(response)})")

    ai_result = extract_json(response)
    # print(f"[DBG RE] _score_one: extract_json type={type(ai_result).__name__}, is_dict={isinstance(ai_result, dict)}")
    if not isinstance(ai_result, dict):
        log(f"[WARN] Unparseable AI response for: {job['title']}", sid)
        return None

    r = _apply_scoring(job, ai_result, min_score, keywords, llm_weight, kw_weight, internship_mode)
    # print(f"[DBG RE] _score_one: result={'PASS' if r else 'REJECTED'}")
    return r


def _score_batch(
    batch_jobs: list[dict],
    min_score: int,
    keywords: Optional[list],
    resume: Optional[str],
    llm_weight: float,
    kw_weight: float,
    internship_mode: bool,
    sid: str = None,
    cancel_check: Optional[callable] = None,
) -> list[dict]:
    print(f"[DBG RE] _score_batch: n={len(batch_jobs)} [{', '.join(j['title'][:40] for j in batch_jobs)}] intern={internship_mode}")
    if cancel_check and cancel_check():
        return []
    prompt = batch_relevance_prompt(
        [(j["title"], j["description"], j.get("tags")) for j in batch_jobs],
        resume=resume,
        internship_mode=internship_mode,
    )
    # print(f"[DBG RE] _score_batch: prompt built, len={len(prompt)}, mode={'internship' if internship_mode else 'normal'}")
    response = ""
    if internship_mode:
        response = _internship_provider.chat(prompt, max_tokens=3000, cancel_check=cancel_check)
        # print(f"[DBG RE] _score_batch: internship_provider.chat() returned {'SUCCESS' if response else 'EMPTY'} (len={len(response)})")
    if not response and not (cancel_check and cancel_check()):
        response = LLMClient.batch_chat(prompt, cancel_check=cancel_check)
        # print(f"[DBG RE] _score_batch: LLMClient.batch_chat() returned {'SUCCESS' if response else 'EMPTY'} (len={len(response)})")

    parsed = extract_json(response)
    # print(f"[DBG RE] _score_batch: extract_json type={type(parsed).__name__}, is_list={isinstance(parsed, list)}, len={len(parsed) if isinstance(parsed, list) else 'N/A'}")
    if not isinstance(parsed, list):
        log(f"[BATCH WARN] Response is not a list — falling back to per-job scoring", sid)
        # print(f"[DBG RE] _score_batch: not a list, falling back to per-job scoring")
        results = []
        for job in batch_jobs:
            if cancel_check and cancel_check():
                break
            r = _score_one(job, min_score, keywords, resume, llm_weight, kw_weight, internship_mode, sid=sid, cancel_check=cancel_check)
            if r:
                results.append(r)
        # print(f"[DBG RE] _score_batch: per-job fallback returned {len(results)} results")
        return results

    results = []
    for job, ai_result in zip(batch_jobs, parsed):
        if not isinstance(ai_result, dict):
            log(f"[BATCH WARN] Invalid entry for '{job['title']}' — skipping", sid)
            # print(f"[DBG RE] _score_batch: invalid entry for '{job['title']}', type={type(ai_result).__name__}")
            continue
        r = _apply_scoring(job, ai_result, min_score, keywords, llm_weight, kw_weight, internship_mode)
        # print(f"[DBG RE] _score_batch: job '{job['title']}' -> {'PASS' if r else 'REJECTED'}")
        if r:
            results.append(r)

    # print(f"[DBG RE] _score_batch: returning {len(results)} results")
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
    sid: str = None,
    cancel_check: Optional[callable] = None,
) -> list:
    print(f"[DBG RE] filter_jobs: {len(jobs)} jobs, min_score={min_score}, intern={internship_mode}")
    if not jobs:
        return []

    log(f"[MATCH ENGINE] {len(jobs)} jobs received", sid)

    limit = llm_candidate_limit * 2 if internship_mode else llm_candidate_limit
    # print(f"[DBG RE] filter_jobs: limit={limit} (internship_boost={'yes' if internship_mode else 'no'})")

    kw_scored = [
        (job, keyword_score(job["title"], job["description"], job.get("tags"), keywords))
        for job in jobs
    ]

    candidates = sorted(kw_scored, key=lambda x: x[1], reverse=True)[:limit]
    print(f"[DBG RE] filter_jobs: top {len(candidates)} kw_scores: {[s for _,s in candidates[:5]]}")

    batch_size = BATCH_SIZE_RATIO[internship_mode]
    # print(f"[DBG RE] filter_jobs: batch_size={batch_size} (internship={internship_mode})")

    log(f"[MATCH ENGINE] {len(candidates)}/{len(jobs)} sent to LLM (limit={llm_candidate_limit}, batch_size={batch_size})", sid)

    candidate_jobs = [job for job, _ in candidates]
    batches = [candidate_jobs[i:i + batch_size] for i in range(0, len(candidate_jobs), batch_size)]

    log(f"[MATCH ENGINE] {len(batches)} batch(es) of up to {batch_size}", sid)

    filtered = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(
                _score_batch, batch, min_score, keywords, resume, llm_weight, kw_weight, internship_mode, sid, cancel_check
            ): f"batch of {len(batch)}"
            for batch in batches
        }
        # print(f"[DBG RE] filter_jobs: submitted {len(futures)} batches to pool (max_workers={max_workers})")
        for future in as_completed(futures):
            if cancel_check and cancel_check():
                log(f"[MATCH ENGINE] Cancelled — discarding remaining LLM batches", sid)
                # print(f"[DBG RE] filter_jobs: cancelled — discarding")
                for f in futures:
                    f.cancel()
                break
            label = futures[future]
            try:
                batch_results = future.result(timeout=90)
                # print(f"[DBG RE] filter_jobs: batch '{label}' returned {len(batch_results)} results")
                for r in batch_results:
                    filtered.append(r)
                    if progress_callback:
                        progress_callback(r)
            except Exception as e:
                log(f"[MATCH ENGINE] Error scoring {label}: {e}", sid)
                # print(f"[DBG RE] filter_jobs: ERROR for {label}: {e}")

    filtered.sort(key=lambda j: j["total_score"], reverse=True)
    print(f"[DBG RE] filter_jobs: final {len(filtered)} relevant, top: {[j['total_score'] for j in filtered[:5]]}")
    log(f"[MATCH ENGINE] {len(filtered)} relevant jobs returned", sid)
    return filtered

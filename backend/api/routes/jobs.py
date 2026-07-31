import hashlib
import threading
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from db import get_raw_jobs, get_session, update_raw_job_score, upsert_referral_score
from utils.logger import log

router = APIRouter(prefix="/jobs", tags=["jobs"])

_scoring_inflight = set()
_scoring_lock = threading.Lock()

MAX_RELEVANCE_CHECKS = 3


def _cache_user_score(email: str, url: str, resume_text: str, score: int) -> None:
    if not email or not url or not resume_text or score <= 0:
        return
    try:
        h = hashlib.md5(resume_text.strip().encode("utf-8", errors="replace")).hexdigest()
        upsert_referral_score(email, url, h, score)
    except Exception:
        pass


class CheckRelevanceRequest(BaseModel):
    search_id: str
    url: str
    resume_text: str = ""
    email: str = ""


def _check_relevance_score(job: dict, keywords: list, resume_text: str, internship_mode: bool, sid: str) -> Optional[dict]:
    from llm.llm_client import LLMClient
    from llm.prompts import relevance_prompt, internship_relevance_prompt
    from utils.json_parser import extract_json
    from match_engine.relevance_engine import keyword_score

    prompt_fn = internship_relevance_prompt if internship_mode else relevance_prompt
    prompt = prompt_fn(job["title"], job.get("description") or "", job.get("tags"), resume=resume_text or None)

    ai_score = None
    reason = ""
    for attempt in range(3):
        response = LLMClient.chat(prompt, max_tokens=800, cancel_check=None)
        parsed = extract_json(response)
        if isinstance(parsed, dict) and isinstance(parsed.get("score"), int):
            ai_score = max(0, min(100, parsed["score"]))
            reason = str(parsed.get("reason", "") or "")
            break
        log(f"[CHECK-RELEVANCE] Unparseable LLM response (attempt {attempt + 1}), retrying", sid)
    if ai_score is None:
        return None

    kw_score = keyword_score(job["title"], job.get("description") or "", job.get("tags"), keywords=keywords or [])
    llm_weight = 0.85 if internship_mode else 0.7
    kw_weight = 0.15 if internship_mode else 0.3
    kw_norm = min(kw_score, 100)
    total_score = round(ai_score * llm_weight + kw_norm * kw_weight)

    return {
        "ai_score": ai_score,
        "keyword_score": kw_score,
        "total_score": total_score,
        "reason": reason,
    }


@router.get("")
async def list_jobs(search_id: str = Query(""), site: str = "",
                    experience_level: str = ""):
    if not search_id:
        return {"total": 0, "jobs": []}
    jobs = get_raw_jobs(search_id)
    if site:
        from utils.url_utils import site_from_url
        jobs = [j for j in jobs if site_from_url(j.get("url", "")) == site]
    if experience_level:
        jobs = [j for j in jobs if j.get("experience_level") == experience_level]
    return {"total": len(jobs), "jobs": jobs}


@router.get("/{index}")
async def get_job(search_id: str = Query(""), index: int = 0):
    if not search_id:
        raise HTTPException(404, "Job not found")
    jobs = get_raw_jobs(search_id)
    if index < 0 or index >= len(jobs):
        raise HTTPException(404, "Job not found")
    return jobs[index]


@router.post("/check-relevance")
def check_relevance(req: CheckRelevanceRequest):
    if not req.search_id or not req.url:
        return {"ok": False, "error": "Missing search_id or url"}
    jobs = get_raw_jobs(req.search_id)
    job = next((j for j in jobs if j.get("url") == req.url), None)
    if job is None:
        return {"ok": False, "error": "Job not found in this search"}

    if job.get("total_score") is not None:
        _cache_user_score(req.email, req.url, req.resume_text, job.get("total_score") or 0)
        return {"ok": True, "score": {
            "total_score": job.get("total_score"),
            "ai_score": job.get("ai_score"),
            "keyword_score": job.get("keyword_score"),
            "reason": job.get("reason", ""),
        }}

    key = (req.search_id, req.url)
    with _scoring_lock:
        if key in _scoring_inflight:
            return {"ok": False, "error": "This job is already being scored"}
        _scoring_inflight.add(key)
    try:
        session = get_session(req.search_id) or {}
        result = _check_relevance_score(
            job,
            keywords=session.get("keywords") or [],
            resume_text=req.resume_text or "",
            internship_mode=session.get("internship_mode", False),
            sid=req.search_id,
        )
        if not result:
            return {"ok": False, "error": "AI could not score this job. Try again."}
        update_raw_job_score(
            req.search_id, req.url,
            ai_score=result.get("ai_score"),
            keyword_score=result.get("keyword_score"),
            total_score=result.get("total_score"),
            reason=result.get("reason", ""),
        )
        _cache_user_score(req.email, req.url, req.resume_text, result.get("total_score") or 0)
        return {"ok": True, "score": {
            "total_score": result.get("total_score"),
            "ai_score": result.get("ai_score"),
            "keyword_score": result.get("keyword_score"),
            "reason": result.get("reason", ""),
        }}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        with _scoring_lock:
            _scoring_inflight.discard(key)

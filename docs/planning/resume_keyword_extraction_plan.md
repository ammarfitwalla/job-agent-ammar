# Resume Keyword Extraction Recall — Plan

> **Status:** proposed · **Date:** 2026-10-05
> **Owner:** backend
> **Trigger:** user feedback — "some keywords are not being extracted and I have to add them manually"

## Problem

Resume keyword extraction under-recalls. Users must manually add skills the extractor missed,
which defeats the point of auto-extract and skews relevance scoring (`total = AI×0.7 + keyword×0.3`).

## Root causes (confirmed)

| # | Cause | Location | Evidence |
|---|---|---|---|
| 1 | Prompt asks for exactly 20 | `resume.py:38` | 62/70 prod sessions return exactly 20 |
| 2 | Only first **2 PDF pages** read | `resume.py:63` | `doc.select(range(min(len(doc), 2)))` |
| 3 | **DOCX tables ignored** | `resume.py:68` | `.paragraphs` excludes table cells where skills usually live |
| 4 | No case-insensitive dedupe | `resume.py:139` | Same resume yielded `Custom Plugin Development` + `custom plugin development` |
| 5 | Truncated reasoning output silently empties the list, UI still reports success | `resume.py:132-153`, `search.js:1194` | `openai/gpt-oss-20b` shares `max_completion_tokens=4000`; `extract_json` returns `None`; 4 prod sessions have only 1-2 keywords |

### Production evidence

`sessions.keywords_count` distribution (252 total sessions, 70 with keywords):

| keywords | sessions |
|---|---|
| 1 | 3 |
| 2 | 1 |
| 19 | 3 |
| **20** | **62** |
| 21 | 1 |

89% of extractions sit exactly on the prompt's "top 20". The `[:30]` code cap never binds —
the prompt is the real ceiling. "Most relevant" also biases toward the dominant stack, so
niche/secondary tools (jQuery, Tailwind, GitHub Actions in a PHP/WordPress resume) get dropped.

### Ruled out

- **PII over-redaction** — tested directly; skill lines survive intact. Only false positive found:
  `"5 years in RD"` → `[address]` (matches the `rd\.?` street-suffix in `_SUFFIX_PATTERN`).
  Certificates, version strings (`Python 3.11, Java 8`), and metric lines all pass through clean.
- **Frontend truncation** — `renderKeywords` maps the full array; no `.slice()`.
- **Resume-text length cap** — `sanitize_resume_text` only redacts PII, no truncation.

## Decisions

| Question | Answer |
|---|---|
| Target keyword count | **~40**, configurable |
| Recall booster | **Industry-agnostic** — no fixed technology list. Works for nursing, law, finance, trades equally well. |
| `keyword_score` | **Normalize** so it's count-independent |

## Changes

### `backend/api/routes/resume.py` (bulk of the work)

- `_extract_text`: read **all** PDF pages up to `RESUME_MAX_PDF_PAGES` (10). For `.docx`, also walk
  `document.tables` (recursively) plus section headers/footers. Return `(text, meta)` with a
  `truncated` flag so the UI reports dropped pages instead of silently hiding them.
- Add `_chunk_text(text, chars, overlap)` — paragraph-aware, no mid-word splits.
- Add `EXTRACT_CHUNK_PROMPT`: keywords **only**, industry-agnostic wording
  ("skills, tools, technologies, certifications, methods, or domains **explicitly written**"),
  no "top N", breadth encouraged. Reuses the existing `{available_roles}` / `{resume}` placeholders
  so `test_role_recommendation.py:113` keeps passing.
- Rewrite `extract_keywords` in two stages:
  - **Profile pass** — whole resume (char-budgeted) → `suggested_roles` (still `[:3]`) + seed keywords.
  - **Recall passes** — one per chunk, keywords only.
  - **Merge** — strip + collapse whitespace, `casefold()` dedupe key, count chunks per term,
    rank by chunk-frequency desc (ties broken profile-pass-first), truncate to `RESUME_MAX_KEYWORDS=40`.
- 3 attempts, JSON validation, truthful response:
  `{"keywords": [...], "suggested_roles": [...], "extraction_ok": bool, "keyword_count": int, "truncated": bool}`
- Run recall passes in a `ThreadPoolExecutor` (`LLMClient` is blocking) so latency doesn't scale linearly.

### `backend/match_engine/relevance_engine.py:102,138`

Currently `keyword_score` is `+10 per matched keyword`, clamped at 100 — so more keywords push more
jobs to the ceiling and flatten ranking discrimination.

```
kw_norm = min(100, round(100 * matches / target))   # target = max(5, min(len(kw_list), 12))
```

A 40-keyword user matching 8 scores the same as a 20-keyword user matching 8. **This changes existing
score distribution** — compute before/after over real cached jobs and get sign-off before shipping.

### `backend/config.example.py` + prod `config.py` (append-only merge, BOM preserved)

`RESUME_MAX_KEYWORDS=40` · `RESUME_MAX_PDF_PAGES=10` · `RESUME_CHUNK_CHARS` · `RESUME_MAX_CHUNKS` ·
`KEYWORD_SCORE_TARGET=12`

### `frontend/js/search.js`

- `renderKeywords` **merges** into existing chips instead of replacing — manual additions and
  unchecked state survive re-extract.
- Status shows `Extracted N keywords`.
- Amber warning when `extraction_ok` is false or `truncated` is true.

## Tests

New `backend/tests/test_resume_extraction.py`:

- multi-page PDF — asserts page 3+ skills appear
- docx with skills **only** in a table
- chunk union + case-variant dedupe
- 40-cap with frequency ranking
- `extraction_ok=false` when the LLM returns junk
- `suggested_roles` still capped at 3

Normalization: bounded ≤100, monotonic, equal score for 20- vs 40-keyword users at equal match count.

## Rollout

1. Land code + tests; run full suite — expect the same **6 baseline failures**, nothing new:
   - `test_linkedin_scraper.py` × 4 (`test_scrape_http_filters_by_location_and_duplicates`,
     `..._internship_mode_uses_intern_fallback`, `..._respects_results_wanted`, `..._returns_empty_for_no_roles`)
   - `test_role_recommendation.py` × 2 (`test_new_roles_present`, `test_valid_response_parses`)
2. Report before/after `kw_norm` distribution on real jobs — **approval gate**.
3. Deploy per `DEPLOYMENT_RUNBOOK.md`: append `RESUME_*` to prod `config.py`, `docker cp` the 3 files,
   `sudo chown -R 1000:1000`, `docker restart`, verify logs + `/app` 200.

## Risks

- Recall passes = up to ~5 LLM calls per extraction against a **28/min Groq token bucket**
  (`providers.py:64`). Mitigate with `RESUME_MAX_CHUNKS`.
- Latency — parallelized via thread pool, but still multiple round trips.
- Scoring change needs `min_score` re-validation (step 2).
- Keyword payload grows; negligible (keywords feed **scoring only**, not scraper queries —
  `scrape.py:136` → `filter_jobs`).

## Fast path (interim)

Landed ahead of the full plan, since 89% of extractions were capped by the prompt alone:

- `resume.py:38` — prompt `top 20` → `top 40`
- `resume.py:139` — `[:30]` → `[:40]`
- `resume.py:146` — `[:30]` → `[:40]` (list fallback)

Both numbers must move together: the prompt binds, the slice is the safety net.

Doesn't address causes 2-5. If feedback persists on long PDFs or table-based resumes, proceed with
the full plan above.
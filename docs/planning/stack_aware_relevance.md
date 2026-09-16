# Stack-Aware Relevance — Implementation Plan

**Goal:** Stop recommending jobs whose required stack conflicts with the user's stack (e.g., a
React developer shown an Angular role). Deterministic, server-side, penalty-only, zero manual input.

**Confirmed decisions**
1. **Learn stack automatically** from `resume_text` + `profile.position`. No manual include/exclude input (now).
2. **Penalty only** — conflicting jobs are ranked lower and shown with a chip, **never removed**.
   Within-tech conflicts: `-35` penalty + amber chip `Stack mismatch: React vs Angular`. Still shown.
3. **Cross-profession conflict = hard-exclude** (deterministic, e.g., resume clearly Lawyer vs a Software
   Engineer posting → job dropped silently, counted in a small notice).
4. **Tech-only catalog** for substitute groups this pass (React↔Angular↔Vue↔Svelte, Flutter↔React Native,
   etc.); media/civil/healthcare/law substitute tables are a later, low-risk data add.
5. Auto detection only — **no query tuning** (scraped queries unchanged; filtering happens server-side).

---

## 1. New module — `backend/match_engine/stack_matcher.py`

Catalog + detection + conflict classification, fully deterministic (no LLM, fast, cacheable).

### 1a. Substitute groups (in-tech conflicts → penalty, still show)

```python
FRONTEND_FRAMEWORKS = [
    {"id", "members": [...], "signals": [...]},
]
SUBSTITUTE_GROUPS = [
    # frameworks
    {"name": "React/Angular/Vue/Svelte", "members": ["react", "angular", "vue", "svelte"], "tiers": {angular: "js"}},
    {"name": "Next/Remix", "members": ["next.js", "remix"]},
    {"name": "Flutter/React Native", "members": ["flutter", "react native"]},
    # languages
    {"name": "Java/C#/.NET", "members": ["java", "c#", "csharp", ".net"]},
    {"name": "Rails/Django/Laravel", "members": ["rails", "django", "laravel"]},
    {"name": "Node/Python generics", "members": ["node", "python"]},
]
```

Variable assignment: `USER_STACK` → chosen member(s) of groups from resume detection.

### 1b. Cross-profession signatures (hard-exclude)

```python
PROFESSION_SIGNS = {
    "tech":       ["software developer", "backend engineer", "react", "typescript", "devops",
                   "ci/cd", "microservices", "rest api", "agile", "scrum", "git"],
    "healthcare": ["nursing", "patient care", "hipaa", "clinical", "physician", "pharmacy",
                   "medical assistant", "care plan", "triaging"],
    "civil":      ["structural", "geotechnical", "for construction", "site work", "earthwork",
                   "permitting", "stormwater", "as-built"],
    "media":      ["broadcast", "reporter", "editorial", "showrunner", "after effects",
                   "premiere", "documentary"],
    "law":        ["attorney", "litigation", "bar admission", "legal brief", "esquire",
                   "counsel", "paralegal"],
    "finance":    ["audit", "financial statements", "sox", "gaap", "portofolio management"],
    "design":     ["figma", "sketch", "adobe xd", "brand guidelines", "visual design"],
}
```

### 1c. Detection

```python
def detect_stack(resume_text, position=None) -> dict:
    """Returns {"domains": [...], "stack": [...]} — deterministic keyword scan of
    combine(resume_text, position). Cached in-memory per (email)."""
def classify_job(job, user_stack) -> dict:
    """Returns {"conflict": bool, "severity": "exclude"|"penalize"|None,
                "conflicting_term": str, "matched_term": str,
                "group": "framework"|"language"|"profession", "chip": str}"""
```

Rules:
- **Exclude** when `job_profession != user_profession` from `PROFESSION_SIGNS` (both confident).
- **Penalize** when same profession (tech) but a substitute-group member appears in title/JD where the
  user's chosen member is different (framework↔framework, language↔language). Never exclude.
- **Flexible phrase guard:** if job says "React or Angular" (or `<member> or <substitute>`), treat as flexible → `no penalty`.

### 1d. Score wiring

```python
STACK_CONFLICT_PENALTY = 35
def stack_penalty(job, user_stack) -> (penalty, classify)
```

`penalty = -35` for in-tech conflict, `None → job excluded` for profession conflict.

---

## 2. Backend integration

### 2a. `backend/match_engine/relevance_engine.py`
- **`filter_jobs(...)`** — new param `user_stack: Optional[dict] = None` (already has `resume`,
  `keywords`, `roles`). Thread through `_score_jobs`/`_score_one`/`_apply_scoring`.
- In `_apply_scoring` / `_apply_scoring deterministics path (`_score_jobs` internals):
  - compute `classify_job(job, user_stack)`;
  - `exclude` → return `None` (job dropped) → caller counts as `stack_excluded`.
  - `penalize` → `total_score -= STACK_CONFLICT_PENALTY`, set `stack_conflict=True`,
    `conflicting_stack=["React", "Angular"]`, `stack_conflict_reason="Stack mismatch"` on result.
- `filter_jobs` gains a **settings shape change**: returns `excluded_stacks` count / `notice` aggregate so the router can report `"Excluded N {domain} roles"`.

### 2b. `backend/api/routes/scrape.py`
- `filter_jobs(...)` callers (`_score_jobs`, `filter_jobs` at ~505/507 in `_run_scrape_guarded`) pass
  `user_stack=req.user_stack`.
- `run_scrape(...)` / `_run_scrape_guarded(...)` accept `user_stack`.
- `ScrapeRequest` (in `api/routes/scrape.py`) — **no** new field; compute server-side (see 2c). Pass through scrape init.

### 2c. Stack resolution from profile (server-side, auto)
- New helper in `stack_matcher.py`: `resolve_user_stack(user_email, resume_text=None) -> dict`
  - load profile `position` + cached `detected_stack` (from resume extraction) via `get_user`/profile;
  - fall back to scan of `resume_text` passed in the scrape request;
  - memoized per email.
- `backend/api/routes/resume.py` — `/resume/keywords` response adds `detected_stack: {"domains":[...], "stack":[...]}` so the frontend can show a "Stack detected" hint without recomputing.

---

## 3. Frontend (minimal)

### 3a. `frontend/js/resume.js`
- After keyword extraction: if `d.detected_stack` present, render a subtle line
  `Stack: React · TypeScript` under the suggested roles (non-blocking hint, no input).

### 3b. `frontend/js/search.js`
- Pass nothing extra (server-side). On results render, read each job's `stack_conflict`:
  - amber chip `Stack mismatch` + the conflicting pair (`React vs Angular`).
  - Results notice appended when the scrape summary includes `"Excluded N {profession} roles"`.

---

## 4. Tests

### 4a. New — `backend/tests/test_stack_matcher.py`
- `test_detect_stack_from_resume_position` — resume mentions React/TS → `domains:["tech"], stack:["React","TypeScript"]`.
- `test_in_tech_conflict_penalizes` — Angular JD → penalize (not exclude), severity=penalize.
- `test_cross_profession_excludes` — Lawyer resume vs Software Engineer job → exclude.
- `test_flexible_or_guard` — "React or Angular" JS → no penalty.
- `test_no_false_positive_python_job` — "Python" as a name (e.g., a "Python" the snake? use real: "Monty Python" show) → not detected.

### 4b. Extend — `backend/tests/test_integration.py`
`TestStackAwareRelevance` (mirror `TestIntegrationRelevancePass` setup):
- React-resume search → Angular job is present but `stack_conflict=True`, ranked after a matching
  React job (or its score < matched job's).
- Lawyer-resume → software job `excluded` (not in results), notice reports count.

---

## 5. Verification
1. `node --check` on edited JS; `py_compile` on touched backend files.
2. `python -m unittest backend.tests.test_stack_matcher backend.tests.test_integration` (full suite green).
3. No commit/push/deploy unless requested.

---

## Out of scope (later passes)
- Editable include/exclude stack input.
- Non-tech substitute tables (media/civil/healthcare/law) — same data structure, low risk.
- Query tuning ("stack mismatch" never narrowed).

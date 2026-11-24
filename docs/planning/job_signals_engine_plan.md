# Tech-Stack & Buying-Signal Lead Engine — Plan

> **Status:** proposed · **Date:** 2026-10-14
> **Owner:** backend
> **Scope this pass:** Phases 1–4 only — schema extension, two-stage extraction pipeline, background worker.
> No API/UI, no embeddings. Feature internal name: **`job_signals`**.

## Goal

Extract tech stack, migration/replacement signals, pain points, and a 0–100 **Lead Heat Score**
from scraped job descriptions, so the platform can surface buying-signal leads (later: search
dashboard, saved-search radar, agency/heat view). Derived from public job posts; kept separate
from the consumer `jobs` / `saved_searches` data and gated behind the existing JWT `auth_guard`.

---

## Reality check — spec assumptions vs. the codebase

The originating spec assumed a pre-existing "FTS5 + ONNX embedding + hash-caching" stack. Verified:
**the foundation does not exist.** This is a greenfield feature.

| Spec assumes | Reality (verified) |
|---|---|
| SQLite **FTS5** + BM25 already filtering | **Zero** FTS references in `backend`. No FTS table, no `MATCH`, no `bm25`. |
| **fastembed / ONNX** embeddings | **None.** `backend/requirements.txt` has no ML/vector deps (no numpy, fastembed, onnx). |
| "Hash-based caching tier" skipping already-extracted JDs | **None.** Only URL-dedup exists; no content hash, no extraction cache. |
| `saved_searches` is a "placeholder for future cron" | ✅ True — table + CRUD exist (`db.py:190`, `:2138-2183`) but **nothing** in `api/` or `scheduler.py` uses them. |
| Feature named "leads" | ⚠️ `leads` / `api/leads` is **taken** by the marketing email-capture form (`db.py:98`, `routes/leads.py`, tests). Name collides. |
| Fallback "Groq → Ollama" | Inaccurate — `_FALLBACK_CHAIN = ["groq"]` only (`llm/llm_client.py:19`). NVIDIA/Ollama are registered but not chained. |

### Facts that make the plan safe

- **FTS5 IS available** on the runtime SQLite (`3.40.1`); `porter` + `unicode61` tokenizers compile. ✅
- Every **wired** scraper returns a full `description`: `indeed` (`indeed_scraper.py:117`),
  `linkedin` (`linkedin_scraper.py:345/:519`), `naukri` (`naukri_scraper.py:275`). ✅
  (`SITE_MAP` in `scrape.py:111-115` wires exactly these three.)
- Durable job text lives in `job_cache.jobs_json` (per-combo array of job dicts) and
  session-scoped `jobs.description`.
- LLM helpers exist: `LLMClient.chat/batch_chat/keyword_chat` (`llm/llm_client.py`),
  `utils/json_parser.extract_json`.
- Worker pattern exists: APScheduler + daemon threads in `scheduler.py`
  (`start_scheduler`, `start_mail_worker`, `start_mail_worker` drains `email_queue` independent
  of `SCHEDULER_ENABLED`); started from `api/main.py` lifespan.

---

## Confirmed decisions

1. **Search layer:** FTS5 only, **no embeddings** this pass. No new dependencies; deploys safely
   via `docker cp` to the existing VM.
2. **Scope tonight:** Phases 1–4 (schema + two-stage pipeline + worker). No API/UI.
3. **Naming:** DB table `job_signals`, module `match_engine/signals.py`, dictionaries
   `match_engine/signal_data.py`, future API prefix `/api/signals`. Avoids the `leads` collision.
4. **Extraction trigger:** reactive hook after cache write **+** a config-capped one-time backfill.
   LLM calls never run inline on the request path.
5. **Alerts (Phase 5+):** email only, reusing `email_queue` + `enqueue_email` + the mail worker.
   No new infrastructure.

---

## Phase 0 — Preconditions (verify, no edits)

- [ ] Confirm each `job_cache.jobs_json` element carries `url` + `description` (needed by the backfill
      iterator and for the `url` primary key).
- [ ] Confirm `save_cache_entry` (`db.py:740`) round-trips `description` untouched.

## Phase 1 — Schema extension (`db.py`, inside `init_db` `executescript`)

Additive only (`CREATE TABLE IF NOT EXISTS ...`), no destructive migration; follows the existing
idempotent style. Add a `schema_version` table to stop the ad-hoc `ALTER TABLE` sprawl.

```sql
CREATE TABLE IF NOT EXISTS job_signals (
    url                 TEXT PRIMARY KEY,
    company             TEXT DEFAULT '',
    title               TEXT DEFAULT '',
    source              TEXT DEFAULT '',          -- indeed | linkedin | naukri
    content_hash        TEXT DEFAULT '',          -- sha256(normalized description)
    schema_version      INTEGER DEFAULT 1,
    extracted_at        TEXT NOT NULL,
    detected_technologies TEXT DEFAULT '[]',      -- JSON array
    migration_signals   TEXT DEFAULT '[]',        -- JSON array
    pain_points         TEXT DEFAULT '[]',        -- JSON array
    role_classification TEXT DEFAULT '',
    lead_heat_score     INTEGER DEFAULT 0,
    scored_by           TEXT DEFAULT 'stage1',    -- 'stage1' | 'stage2'
    evidence_text       TEXT DEFAULT '',          -- text fed to FTS
    raw_json            TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_signals_company ON job_signals(company);
CREATE INDEX IF NOT EXISTS idx_signals_heat    ON job_signals(lead_heat_score);
CREATE INDEX IF NOT EXISTS idx_signals_age     ON job_signals(extracted_at);
CREATE INDEX IF NOT EXISTS idx_signals_source  ON job_signals(source);

CREATE VIRTUAL TABLE IF NOT EXISTS job_signals_fts
    USING fts5(evidence_text, content='job_signals', content_rowid='rowid',
               tokenize='porter unicode61');

CREATE TABLE IF NOT EXISTS signal_queue (
    url             TEXT PRIMARY KEY,
    status          TEXT DEFAULT 'pending',       -- pending | running | done | failed
    attempts        INTEGER DEFAULT 0,
    enqueued_at     TEXT NOT NULL,
    last_attempt_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_signal_queue_status ON signal_queue(status, enqueued_at);

CREATE TABLE IF NOT EXISTS schema_version (
    id      INTEGER PRIMARY KEY CHECK (id = 1),
    version INTEGER NOT NULL
);
```

Keep `job_signals_fts` in sync via `AFTER INSERT/UPDATE/DELETE` triggers on `job_signals`
(or manual sync inside `save_signal`).

**New db.py functions:** `save_signal`, `get_signal`, `signal_exists(content_hash)`,
`enqueue_signal(url, source)`, `claim_signal_batch(limit)`, `mark_signal_done`, `mark_signal_failed`,
`search_signals(filters, fts_query)` (FTS `MATCH` + column filters).

## Phase 2 — Stage-1 deterministic extractor

### `match_engine/signal_data.py` (new)
- Tech dictionary (~150 terms) with alias normalization (`k8s → kubernetes`, `postgres → postgresql`, …).
- Migration / replacement phrase list (`"migrating off"`, `"replacing"`, `"legacy"`, `"rip and replace"`, …).
- Pain-point phrase list.
- Reuse `SENIORITY_WORDS` / `ABBREVIATIONS` from `llm/prompts.py`.

### `match_engine/signals.py` (new)
- `content_hash(description) -> str` — sha256 of normalized text.
- `extract_stage1(text) -> dict` — cheap keyword/regex extraction → technologies, migration signals,
  pain points, role class.
- `compute_lead_heat(seniority, hiring_velocity, recency) -> int` — **deterministic** formula.
  Hiring velocity = recent role count per company aggregated from `jobs` / `job_cache`.

## Phase 3 — Stage-2 LLM extractor

- New `SIGNAL_EXTRACTION_PROMPT` in `llm/prompts.py` returning strict JSON:
  `detected_technologies[]`, `migration_signals[]`, `pain_points[]`, `role_classification`,
  optional qualitative heat bump.
- Parse with `utils/json_parser.extract_json`; batch via `LLMClient.batch_chat`; cap per run via config.
- **Hash-skip guard:** if `content_hash` already present in `job_signals`, skip the LLM entirely
  (this is the "caching tier" the original spec assumed existed).
- Persist with `scored_by='stage2'`, superseding the Stage-1 row.

## Phase 4 — Pipeline wiring

- `scheduler.py`: add `start_signal_worker()` daemon thread (mirrors `start_mail_worker`), draining
  `signal_queue` under the existing `scheduler_lock` pattern; add `stop_signal_worker()`.
- Config knobs (`config.py`, lazy `getattr` pattern): `SIGNALS_ENABLED`, `SIGNAL_BATCH_SIZE`,
  `SIGNAL_BACKFILL_MAX`.
- Hook in `api/routes/scrape.py`: after `save_cache_entry` (~`:419`) and/or after
  `_harvest_companies` (~`:519`), enqueue **newly-seen** URLs only (dedup by `url` + `content_hash`).
- One-time capped backfill over existing `jobs` / `job_cache` on boot.
- Register/start the worker in the `api/main.py` lifespan.

---

## Explicitly deferred (Phase 5+)

- `GET/POST /api/signals/search` endpoint (FTS `MATCH` + boolean tech queries + filters).
- Wire existing `saved_searches` → **radar alerts** via `enqueue_email` + mail worker (email only).
- Optional Slack incoming-webhook sender (new config key + small util).
- Agency / heat dashboard in the frontend.

---

## Verification

- New `backend/tests/test_signals.py`: dictionary normalization/alias, `content_hash` dedup,
  lead-heat formula determinism, FTS search round-trip (insert → `MATCH` → expected rows).
- Extend `backend/tests/test_integration.py` for `init_db()` idempotency (re-run creates no dupes).
- Run existing suites. **Baseline failures unrelated to this work:**
  `test_linkedin_scraper.py` (4× `test_scrape_http_*`);
  `test_role_recommendation.py` (`test_new_roles_present`, `test_valid_response_parses`).

## Deployment

- Additive schema + new background worker deploy via `docker cp` + `docker restart` per
  `docs/deployment/DEPLOYMENT_RUNBOOK.md`. **Never recreate `job-agent`.** Keep isolated from the
  separate portfolio workstream.

## Open items carried from prerequisites

- Real years-of-experience value unknown (`#years` `data-count="0"` on the portfolio) — unrelated to
  this feature, tracked elsewhere.
- Web3Forms key unavailable — unrelated to this feature.

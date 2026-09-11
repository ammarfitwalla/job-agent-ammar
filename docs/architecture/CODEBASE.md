# Codebase Documentation — Job Agent

> Automated job scraper + AI scoring + referral marketplace + web dashboard.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Project Structure](#project-structure)
3. [Backend](#backend)
   - [FastAPI Entry Point](#fastapi-entry-point)
   - [Auth & Security (JWT)](#auth--security-jwt)
   - [Database Layer](#database-layer)
   - [API Routes](#api-routes)
   - [Scrapers](#scrapers)
   - [LLM Integration](#llm-integration)
   - [Match Engine](#match-engine)
   - [Utilities](#utilities)
4. [Scheduler & Job Cache](#scheduler--job-cache)
5. [Frontend](#frontend)
   - [Pages](#pages)
   - [JavaScript Modules](#javascript-modules)
6. [Infrastructure](#infrastructure)
7. [Configuration](#configuration)
8. [API Reference](#api-reference)
9. [Data Flow](#data-flow)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        FRONTEND                                     │
│   landing.html   index.html(/app)  profile.html  admin.html         │
│   search.js      profile.js        admin.js      referrals.js       │
│   auth.js        api.js            jobs.js       utils.js           │
│   constants.js   terms.js                                          │
├─────────────────────────────────────────────────────────────────────┤
│                    FastAPI (api/main.py, 308 lines)                 │
│   JWT auth_guard middleware (Bearer tokens, admin class, whitelist) │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────────┐   │
│  │ Scrape   │ │ Jobs     │ │ Auth     │ │ Profile/Saved/Referal │  │
│  │ Routes   │ │ Routes   │ │ Routes   │ │ Routes (+ joblink)   │  │
│  └────┬─────┘ └───┬──────┘ └──────────┘ └──────────────────────┘   │
│       │           │                                                 │
│  ┌────▼───────────▼────┐   ┌────────────────┐   ┌──────────────┐   │
│  │  Scrapers (8 sites) │   │ Match Engine   │   │ Job Cache +  │   │
│  │  importlib, browser │   │ (relevance)    │   │ Prewarm       │   │
│  └────┬───────────┬────┘   └───┬────────────┘   ├──────────────┤   │
│       │           │            │                │ Scheduler    │   │
│  ┌────▼───────────▼────────────▼────┐  ┌────────▼────────────┐   │
│  │      LLM Client (Groq → Ollama)  │  │ Database (SQLite)   │   │
│  └──────────────────────────────────┘  │ 18 tables           │   │
├─────────────────────────────────────────┴─────────────────────┴─────┤
│                     SQLite (job_agent.db)                            │
└──────────────────────────────────────────────────────────────────────┘
```

**Request lifecycle:**
1. Every `/api/*` (non-whitelisted) request hits the JWT `auth_guard` middleware → `401` if the Bearer token is missing/expired; admin-class paths additionally require `email == ADMIN_EMAIL` (`403` otherwise).
2. Search results are served **cache-first** from the `job_cache` table when a prewarmed/matchable entry exists (instant response); otherwise a scrape is started.
3. `POST /scrape` runs scrapers in a background thread → raw jobs → `relevance_engine.filter_jobs()` → LLM-scored + keyword-scored → results streamed to `sessions.jobs`.
4. Frontend polls `GET /scrape/status` every 3 seconds and renders results.
5. A DB-backed **prewarm scheduler** continuously fills `job_cache` ahead of demand so user searches hit instantly.

---

## Project Structure

```
job-agent-ammar/
├── backend/
│   ├── api/
│   │   ├── main.py              # FastAPI app, JWT auth_guard, routers, static mount
│   │   ├── deps.py              # get_current_user / get_optional_user (JWT -> email)
│   │   ├── schemas.py           # Pydantic models (Job, ScrapeRequest, etc.)
│   │   └── routes/
│   │       ├── admin.py         # Admin dashboard, DB restore/merge, cache/prewarm stats
│   │       ├── auth.py          # Email OTP login (returns JWT), register, companies
│   │       ├── email.py         # (# stub) Daily report emails
│   │       ├── events.py        # Client-side event logging (public)
│   │       ├── joblink.py       # Resolve job URL -> company via aliases/slugs
│   │       ├── jobs.py          # Read scored jobs for a session
│   │       ├── leads.py         # Lead capture + admin lead list
│   │       ├── profile.py       # Profile CRUD, resume upload, refer opt-in
│   │       ├── referrals.py     # Referral requests, dual-confirm, invite, score
│   │       ├── resume.py        # Resume upload, keywords, ZIP download, storage mgmt
│   │       ├── roles.py         # Role categories + custom roles
│   │       ├── saved_jobs.py    # Saved jobs CRUD + batch check
│   │       ├── scrape.py        # Scrape orchestrator (cache-first, combos, stop/status)
│   │       ├── states.py        # Country/state data (public)
│   │       ├── stats.py         # Public stats
│   │       ├── users.py         # Referrer discovery (privacy-scrubbed)
│   │       └── visits.py        # Visit tracking beacons (public)
│   ├── llm/
│   │   ├── llm_client.py        # Unified dispatcher: Groq → Ollama fallback
│   │   ├── prompts.py           # Prompt templates (scoring, keywords, cover letters)
│   │   └── providers.py         # Groq + Ollama providers, rate limits, backoff
│   ├── match_engine/
│   │   ├── relevance_engine.py  # Keyword + AI scoring, filtering, batching
│   │   └── resume_data.py       # Loads resume.txt at import time
│   ├── scrapers/
│   │   ├── adzuna_scraper.py    # Adzuna API (multi-country)
│   │   ├── eurojobs_scraper.py  # EuroJobs (browser scraping)
│   │   ├── gulftalent_scraper.py# GulfTalent (browser scraping)
│   │   ├── indeed_scraper.py    # Indeed via raw HTTP (country domains)
│   │   ├── linkedin_scraper.py  # LinkedIn HTTP + guest API (primary)
│   │   ├── linkedin_scraper_playwright.py # LinkedIn via JobSpy (fallback)
│   │   ├── naukri_scraper.py    # Naukri (browser scraping, optional proxy)
│   │   ├── remoteok_scraper.py  # RemoteOK JSON API
│   │   └── weworkremotely_scraper.py # WeWorkRemotely (browser scraping)
│   ├── auto_apply/
│   │   ├── base_apply.py        # Auto-apply base class
│   │   └── remoteok_apply.py    # RemoteOK auto-apply
│   ├── utils/
│   │   ├── client_ip.py         # Client IP extraction (behind proxies)
│   │   ├── delay.py             # Random sleep (anti-detection)
│   │   ├── experience_level.py  # Job level detection (intern/entry/senior)
│   │   ├── json_parser.py       # Extract JSON from LLM responses
│   │   ├── jwt.py               # create_token / decode_token / ensure_secret (pure stdlib)
│   │   ├── logger.py            # File + console logging
│   │   ├── pii.py               # PII scrubbing (redaction helpers)
│   │   ├── rate_limiter.py      # In-memory rate limiter
│   │   ├── smtp_sender.py       # SMTP email sending (verification codes)
│   │   └── visitor_log.py       # Visit logging helpers
│   ├── emails/
│   │   └── daily_report.py      # Daily email report
│   ├── sheets/
│   │   └── sheets_writer.py     # Google Sheets integration
│   ├── tests/
│   │   ├── test_features.py     # Feature tests
│   │   └── test_integration.py  # Integration tests (JWT auth, 60 tests)
│   ├── db.py                    # SQLite layer (1892 lines, 18 tables)
│   ├── config.py                # Runtime config (GITIGNORED — hardcoded JWT_SECRET+
│   │                            #   keys live here; server copy is source of truth)
│   ├── config.example.py        # Config template
│   ├── scheduler.py             # Self-healing prewarm scheduler (job_cache filler)
│   ├── main.py                  # CLI orchestrator (non-API mode)
│   ├── browser.py               # Undetected-chromedriver helper
│   ├── requirements.txt         # Python dependencies
│   └── Dockerfile               # Production Docker build
├── frontend/
│   ├── landing.html             # Public landing page  (route `/`)
│   ├── index.html               # Search app (route `/app`)
│   ├── profile.html             # User dashboard (saved jobs + referrals)
│   ├── admin.html               # Admin analytics dashboard
│   ├── terms.html               # Terms of service
│   ├── style.css                # Global stylesheet
│   └── js/
│       ├── constants.js         # DEV_MODE, EmailJS credentials, limits
│       ├── utils.js             # Profile state, toast, HTML escaping
│       ├── api.js               # window.api() — Bearer header, cached fetch, 401 handling
│       ├── auth.js              # OTP modal, token/session storage, login gate
│       ├── search.js            # Core search UI (2297 lines, largest file)
│       ├── jobs.js              # Saved job tracker (profile page)
│       ├── profile.js           # Profile management
│       ├── referrals.js         # Referral system UI (1060 lines)
│       ├── admin.js             # Admin dashboard logic
│       └── terms.js             # Terms page helpers
├── resumes/                     # Uploaded resume files (gitignored)
├── Dockerfile                   # HuggingFace Spaces build
├── render.yaml                  # Render.com deployment config
├── scripts/                     # Ops scripts
│   ├── deploy-oracle.sh         # Oracle VM deploy helper
│   └── fetch_server_logs.py     # Pull container logs
└── docs/
    ├── README.md                # Docs index
    ├── architecture/            # Current-system references
    │   ├── CODEBASE.md          # This document
    │   ├── HOW_IT_WORKS.md      # User-facing scoring explanation
    │   └── JWT_AUTH.md          # JWT auth flow walkthrough
    ├── planning/                # Historical plans & task lists
    ├── deployment/              # Ops guides and records
    │   └── jwt_deploy_runbook.md# Production deploy/rollback runbook (Oracle box)
    └── project/                 # Project summaries
```

---

## Backend

### FastAPI Entry Point

**File:** `backend/api/main.py` (308 lines)

- Creates the FastAPI app with CORS (`allow_origins=["*"]`)
- **JWT startup fail-fast:** `lifespan()` calls `utils.jwt.ensure_secret()` — a missing `JWT_SECRET` aborts startup with a clear error (no runtime default).
- Starts/stops the prewarm scheduler on startup/shutdown (tolerates scheduler failures).
- Registers **17 routers**: jobs, scrape, resume, roles, states, events, leads, admin, auth, profile, saved_jobs, visits, users, referrals, stats, joblink (+ votes handled inline).
- **No-cache middleware:** sets `Cache-Control: no-cache` on `/`, `/app`, `/admin`, `/profile`, `.html`, `.css`, `/js/*` so frontend deploys reach users instantly.
- Serves HTML pages: `/` → `landing.html`, `/app` → `index.html`, `/profile` → `profile.html`, `/admin` → `admin.html`.
- Catch-all static mount at `/` (must be last).
- Other endpoints: `/health`, `/votes` (GET/POST), `DELETE /votes` (admin), `/db` (downloads DB), `/logs` (plain-text visit log).

See [Auth & Security (JWT)](#auth--security-jwt) for the `auth_guard` middleware.

---

### Auth & Security (JWT)

**Files:** `backend/utils/jwt.py` (74 lines), `backend/api/deps.py` (32 lines), guard logic in `main.py`.

Stateless, signed, expiring JWT tokens (**HS256**, pure stdlib — no PyJWT dependency).

| Piece | Details |
|-------|---------|
| `create_token(email, expires_minutes=...)` | Mints a token; default expiry from `JWT_ACCESS_TOKEN_MINUTES` (default `1440` = 24h) |
| `decode_token(token)` | Verifies signature + expiry; raises `JwtError` on any failure |
| `ensure_secret()` | Startup guard — refuses to run with an empty/unset `JWT_SECRET` |
| `get_current_user` / `get_optional_user` | FastAPI dependencies → `{"email": sub}` from the verified token |

**Config (config.py):** `JWT_SECRET` (hardcoded with env override; **gitignored**), `JWT_ALLOW_DEV_SECRET`, `JWT_ACCESS_TOKEN_MINUTES`, `ADMIN_EMAIL`.

**The `auth_guard` middleware** (default-deny for `/api/*`):

| Class | Examples | Requirement |
|-------|----------|-------------|
| Public whitelist | `/`, `/app`, `/profile`, `/admin`, `/health`, `/js/*`, `/api/stats/public`, `/api/auth/send-code`, `/api/auth/verify-code`, `/api/users/at-company`, `/api/users/company-counts`, `/api/users/referrer-directory`, `/api/lead`, `/api/events`, `/api/referrals/resolve-url`, `/api/visit/*`, `/scrape*`, `/states`, `/roles`, `/jobs`, GET `/api/auth/companies` | None |
| Protected `/api/*` | `/api/profile*`, `/api/saved-jobs*`, `/api/referrals/*` (except public ones), POST `/api/auth/companies`, POST `/api/auth/register`, `/roles/custom` | Valid token → else `401` |
| Admin | `/api/admin/*`, `/api/leads`, `/api/referrals/notifies`, `/db`, `/logs`, `/docs`, `/redoc`, `/openapi.json`, `/resume/download`, `/resume/storage`, `DELETE /votes` | Token **and** `email == ADMIN_EMAIL` (`401` no token, `403` wrong admin) |

- `OPTIONS` preflights always pass.
- In dev (`JWT_ALLOW_DEV_SECRET=1`) the OpenAPI docs are public; in prod they are admin-only.
- Login flow: `POST /api/auth/send-code` (public) → `POST /api/auth/verify-code` (public) → returns `{token, user}` → browser stores token in **sessionStorage** (`ja_token`) → `window.api()` attaches `Authorization: Bearer <token>` → `401` clears the token and fires `ja:auth-required` (debounced 60s) to re-show the login modal.
- Protected routes trust the token, not client params: e.g. `/api/profile` serves the token's email, `/api/auth/register` rejects a non-matching email (`403`), saved-job ownership is checked via `db.get_saved_job_owner`.

Full step-by-step walkthrough: **`docs/architecture/JWT_AUTH.md`**.

---

### Database Layer

**File:** `backend/db.py` (1892 lines)

SQLite database with WAL mode, busy timeout (5s), and a global write lock (`threading.Lock`).

**Tables (18):**

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `sessions` | Search sessions | `id`, `status`, `internship_mode`, `pass_num`, `max_passes`, `sites`, `keywords`, `roles`, `location`, `resume_filename` |
| `jobs` | Scored job listings | `session_id`, `title`, `company`, `url`, `ai_score`, `keyword_score`, `total_score`, `reason`, `is_raw` |
| `events` | Session event log | `session_id`, `event`, `data`, `elapsed_seconds` |
| `leads` | Captured leads | `email`, `name`, `roles`, `resume_snippet`, `source` |
| `users` | Registered users | `email` (PK), `name`, `company`, `position`, `linkedin_url`, `resume_filename`, `referral_credits`, `refer_opt_in`, `invited_by`, `invite_bonus_awarded`, `referrer_key` |
| `verification_codes` | OTP codes | `email`, `code`, `expires_at`, `used` |
| `visits` | Page visit tracking | `visit_id`, `ip_address`, `user_agent`, `device_type`, `duration_seconds`, `country`, `city` |
| `saved_jobs` | User-saved jobs | `user_email`, `title`, `company`, `url`, `application_status`, UNIQUE(`user_email`, `url`) |
| `saved_searches` | Saved search configs | `email`, `sites`, `keywords`, `roles`, `location`, `interval_hours` |
| `referral_requests` | Referral requests | `from_email`, `to_email`, `job_url`, `status`, `credit_awarded`, `receiver_confirmed`, `sender_confirmed` |
| `custom_companies` | User-added companies | `name` (UNIQUE) |
| `custom_roles` | User-added roles | `name` (UNIQUE) |
| `referral_scores` | Cached LLM match scores per referral job | `from_email`, `job_url`, `resume_hash`, `score` |
| `referral_notifies` | Admin referral notifications | `email`, `company`, `created_at` |
| `job_cache` | Pre-cached scraped jobs (instant search) | `role`, `site`, `city`/`state`/`country`, `internship_mode`, `is_remote`, `created_at`, JSON `jobs` |
| `prewarm_queue` | Prewarm task grid | `role`, `site`, `city`, `state`, `country`, `internship_mode`, `last_run`, `last_job_count` |
| `scheduler_lock` | Single-owner DB lock for the scheduler | `owner`, `last_heartbeat` |
| `custom_prewarm` | User-search-triggered prewarm combos | `role`, `site`, `city`, `state`, `country`, `hours_old`, `usage_count`, `last_run` |

**Key DB functions (grouped by domain):**

| Domain | Functions |
|--------|-----------|
| Sessions | `create_session()`, `update_session()`, `get_session()`, `gc_sessions()` |
| Jobs | `set_raw_jobs()`, `get_raw_jobs()`, `count_raw_jobs()`, `set_filtered_jobs()`, `add_filtered_job()`, `get_filtered_jobs()`, `count_filtered_jobs()`, `update_raw_job_score()` |
| Events | `add_event()`, `get_events()` |
| Leads | `add_lead()`, `get_leads()` |
| Users | `get_user()`, `get_all_users()`, `create_user()`, `update_user_name()`, `update_user_profile()`, `update_user_admin()`, `update_user_refer_opt_in()`, `set_user_invited_by()`, `credit_invite_bonus()`, `referrer_key()`, `get_user_by_referrer_key()` |
| Auth | `save_verification_code()`, `verify_code()` |
| Saved Jobs | `add_saved_job()`, `is_job_saved()`, `batch_check_saved()`, `get_saved_jobs()`, `get_saved_jobs_status_counts()`, `update_saved_job_status()`, `delete_saved_job()`, `get_saved_job_owner()` |
| Saved Searches | `add_saved_search()`, `get_saved_searches()`, `delete_saved_search()` |
| Referrals | `create_referral_request()`, `get_referral_request()`, `get_incoming_referrals()`, `get_outgoing_referrals()`, `get_pending_referral()`, `update_referral_status()`, `complete_referral()`, `confirm_referral()`, `get_monthly_sent_count()`, `upsert_referral_score()`, `get_referral_score()`, `get_latest_referral_scores()` |
| Referral Notifies | `add_referral_notify()`, `get_referral_notifies()` |
| Directory | `get_users_by_company()`, `get_company_user_counts()`, `get_anonymous_referrers_by_company()`, `get_company_referrer_counts()`, `get_company_directory()`, `get_distinct_companies()` |
| Companies | `add_custom_company()`, `batch_add_custom_companies()`, `get_custom_companies()` |
| Custom Roles | `add_custom_role()`, `delete_custom_role()`, `get_custom_roles()` |
| Visits | `log_visit_start()`, `update_visit_ping()`, `finalize_visit()`, `get_visit_stats()`, `get_visits()` |
| Job Cache | `get_cache_entry()`, `save_cache_entry()`, `get_cached_jobs()`, `_cache_key()`, `gc_job_cache()`, `increment_combo_usage()`, `touch_prewarm_combo()` |
| Prewarm | `seed_prewarm_queue()`, `get_prewarm_queue()`, `upsert_prewarm_combo()`, `get_custom_prewarm()`, `upsert_custom_prewarm()`, `remove_custom_prewarm()`, `gc_custom_prewarm()`, `increment_custom_prewarm_usage()` |
| Geolocation | `_resolve_ip_sync()` — IP → country/city/region via ip-api.com with 24h cache; `_store_geo()` |

**Migration strategy:** `init_db()` runs `ALTER TABLE ... ADD COLUMN` inside try/except blocks to add new columns to existing tables without crashing.

---

### API Routes

**Auth classes** (enforced by middleware in `main.py`): 🔓 = public, 🔐 = token required, 👑 = admin.

#### Scrape Routes (`/scrape`)

**File:** `backend/api/routes/scrape.py` (928 lines) — the core orchestrator.

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/scrape` | POST | 🔓 | Starts a background scrape. Cache-first: if a `job_cache` hit exists for the role/site/location combo it returns instantly; otherwise scrapes in a thread |
| `/scrape/stop` | POST | 🔓 | Cancels a running scrape (`cancel=1` in the session) |
| `/scrape/status` | GET | 🔓 | Polls progress: status, pass number, queue position, elapsed time, log messages |

**Scrape pipeline:** resolves location → splits into city/state combos per site (`_build_city_state_map`, `_state_cities`) → each combo checks the job cache (`_cache_lookup`) → live scrapes run `_scrape_combos` (per-board concurrency caps) → raw jobs saved → `_score_jobs` (relevance engine) → results streamed into `jobs`.

**Stale session cleanup:** a daemon thread runs every 60s cancelling sessions older than 15 minutes.

**Company harvesting:** new companies from scored jobs are persisted to `custom_companies`.

**Config knobs per combo** (`_combo_knob`): `CACHE_MIN_VOLUME`, `CACHE_PREWARM_LIMIT`, `CACHE_HOURS_OLD`, etc.

---

#### Auth Routes (`/api/auth`)

**File:** `backend/api/routes/auth.py` (164 lines)

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/api/auth/send-code` | POST | 🔓 | Generates 6-digit OTP, stores in DB with 10min expiry, emails it (SMTP). Rate-limited 3/min per email |
| `/api/auth/verify-code` | POST | 🔓 | Verifies OTP, auto-creates user if new, **returns `{ok, token, user}` — the JWT**. Rate-limited 5/5min |
| `/api/auth/register` | POST | 🔐 | Saves employment info (name, company, position, LinkedIn). Email must **match the token** (`403` otherwise); copies resume from a search_id; applies invite credits |
| `/api/auth/companies` | GET | 🔓 | Curated + custom company list |
| `/api/auth/companies` | POST | 🔐 | Adds a custom company. Rate-limited 5/min per **IP** |

**OTP delivery:** production sends a real code via `utils.smtp_sender`; if SMTP fails it falls back to returning the code in the response. `DEV_MODE = False` at runtime.

**Invite bonus:** registering with `invited_by` grants +5 credits to both the invitee and inviter (and auto-opts the invitee in as a referrer).

---

#### Profile Routes (`/api/profile`)

**File:** `backend/api/routes/profile.py` (123 lines) — all 🔐 token-scoped.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/profile` | GET | Returns the token user's profile + saved job status counts |
| `/api/profile` | PUT | Updates name, company, position, LinkedIn |
| `/api/profile/name` | PUT | Updates name only (profile page quick edit) |
| `/api/profile/refer-opt-in` | PUT | Toggles `refer_opt_in` (appears in company directory) |
| `/api/profile/resume` | POST | Uploads resume (PDF/DOCX/TXT) → stored as `<email-local-part>.<ext>` |
| `/api/profile/resume` | GET | Streams the uploaded resume |
| `/api/profile/resume/text` | GET | Returns extracted plain text of the resume (used by referral scoring) |

---

#### Saved Jobs Routes (`/api/saved-jobs`)

**File:** `backend/api/routes/saved_jobs.py` (88 lines) — all 🔐 token-scoped (identity from token).

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/saved-jobs` | POST | Saves a job for the token user |
| `/api/saved-jobs` | GET | Lists saved jobs (optional `status` filter) |
| `/api/saved-jobs/check` | GET | Is a specific URL saved? |
| `/api/saved-jobs/batch-check` | POST | Bulk check multiple URLs (search page) |
| `/api/saved-jobs/{job_id}/status` | PATCH | Updates application status (saved/applied/interviewing/offer/rejected) |
| `/api/saved-jobs/{job_id}` | DELETE | Removes saved job (ownership-checked via `get_saved_job_owner`) |

---

#### Referral Routes (`/api/referrals`)

**File:** `backend/api/routes/referrals.py` (332 lines) — mixed auth.

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/api/referrals/request` | POST | 🔐 | Send referral request. Rate-limited, monthly limit (5), duplicate check |
| `/api/referrals/incoming` | GET | 🔐 | Requests sent to the token user |
| `/api/referrals/outgoing` | GET | 🔐 | Requests sent by the token user |
| `/api/referrals/{id}/accept` | PUT | 🔐 | Accept → reveals requester's contact info to receiver |
| `/api/referrals/{id}/decline` | PUT | 🔐 | Decline request |
| `/api/referrals/{id}/complete` | PUT | 🔐 | Receiver confirms referral (dual-confirmation) |
| `/api/referrals/{id}/confirm` | PUT | 🔐 | Sender confirms referral (dual-confirmation) |
| `/api/referrals/{id}/withdraw` | PUT | 🔐 | Cancel pending outgoing request |
| `/api/referrals/remaining` | GET | 🔐 | Remaining monthly request count |
| `/api/referrals/score` | POST | 🔐 | Rate-limits + LLM-scores a job against the user's resume (cached in `referral_scores` by resume hash) |
| `/api/referrals/notify` | POST | 🔐 | Adds an admin notification ("someone wants a referral at @Company") |
| `/api/referrals/invite` | POST | 🔐 | Sends an invite email + applies invite credits |
| `/api/referrals/resolve-url` | POST | 🔓 | Job-URL → company resolution (aliases/slugs); IP rate-limited when anonymous |
| `/api/referrals/notifies` | GET | 👑 | Admin list of referral notifications |
| `/api/referrals/resume` | GET | 🔐 | Gets the resume text to prefill the referral request |

**Dual-confirmation:** referrer and requester must both confirm within 48 hours of acceptance → the referrer earns 10 credits.

**Privacy:** directory lookups return opaque IDs; the referrer's identity is only revealed to the accepted requester.

---

#### Other Routes

| File | Prefix | Auth | Endpoints |
|------|--------|------|-----------|
| `joblink.py` | `/api/referrals/resolve-url` | 🔓 | Resolves any job URL → company via Greenhouse/Lever/etc. slug tables, LinkedIn org slugs, domain heuristics |
| `jobs.py` | `/jobs` | 🔓 | `GET /jobs` (filter by min_score/site/experience_level/sort), `GET /jobs/{index}`, `POST /jobs/check-relevance` |
| `resume.py` | `/resume` | mixed | `POST /resume/upload` 🔓 (search page), `POST /resume/keywords` 🔓 (LLM keyword extraction), `GET /resume/download` 👑 (ZIP of all resumes), `DELETE /resume/storage` 👑 |
| `roles.py` | `/roles` | mixed | `GET /roles` 🔓 (categorized roles), `POST /roles/custom` 🔐, `DELETE /roles/custom` 🔐 |
| `states.py` | `/states` | 🔓 | Country/state data with caching |
| `events.py` | `/api/events` | 🔓 | Client event logging (`POST /api/events`) |
| `leads.py` | `/api` | mixed | `POST /api/lead` 🔓, `GET /api/leads` 👑 |
| `visits.py` | `/api/visit` | 🔓 | `POST start`, `POST ping`, `POST end` (beacons) |
| `users.py` | `/api/users` | mixed | `GET at-company` 🔓 (IP rate-limited, privacy-scrubbed), `GET company-counts` 🔓 (optional token excludes self), `GET referrer-directory` 🔓 |
| `stats.py` | `/api/stats` | 🔓 | `GET /api/stats/public` (searches/jobs/matches counts) |
| `admin.py` | `/api/admin` | 👑 all | Stats, sessions, session detail + resume, scores, registrations, user create/patch, visits, leads, DB info/restore/merge, resume upload, custom-prewarm (get/list/delete), usage, cache-stats, server info |

---

### Scrapers

9 scraper modules (8 live boards), all returning a standardized list of dicts: `title`, `company`, `location`, `url`, `description`, `tags`, `salary`.

| Scraper | Site | Method | Lines | Notes |
|---------|------|--------|-------|-------|
| `remoteok_scraper.py` | RemoteOK | JSON API (`/api`) | 80 | Fuzzy role matching, paginated |
| `weworkremotely_scraper.py` | WeWorkRemotely | Browser scraping | 71 | Fetches job pages for descriptions |
| `adzuna_scraper.py` | Adzuna | REST API | 163 | Multi-country, requires API keys |
| `indeed_scraper.py` | Indeed | raw HTTP | 129 | Country-specific domains, salary parsing |
| `linkedin_scraper.py` | LinkedIn | HTTP + guest API | 565 | Primary; rotates user agents, parallel description fetch |
| `linkedin_scraper_playwright.py` | LinkedIn | JobSpy (Playwright) | 238 | Fallback when HTTP scraper fails |
| `naukri_scraper.py` | Naukri | Browser scraping | 338 | Optionally routed via free proxies (`NAUKRI_USE_PROXY`) |
| `gulftalent_scraper.py` | GulfTalent | Browser scraping | 74 | Gulf region |
| `eurojobs_scraper.py` | EuroJobs | Browser scraping | 105 | European job portal |

**Browser scraping:** Uses `undetected-chromedriver` via `browser.py`; random 2-4s delays.

**Internship mode:** Scrapers append "intern" to queries and filter by tech keywords when `internship_mode=True`.

**Role matching:** word-overlap matching (`_role_matches()`) — ≥60% significant-word overlap, with compound-word fallback.

---

### LLM Integration

#### Client (`backend/llm/llm_client.py`, 66 lines)

Unified dispatcher with fallback chain:
```
Primary Provider (configurable: groq) → Ollama
```
- `LLMClient.chat()` — single-job prompts
- `LLMClient.batch_chat()` — batch scoring prompts
- Falls back on empty/failed responses; cooperative cancellation via `cancel_check`.

#### Providers (`backend/llm/providers.py`, 131 lines)

| Provider | Library | Rate Limit | Retries | Backoff |
|----------|---------|------------|---------|---------|
| Groq | `groq` | 28 req/min | 3 (rate-limit only) | 10s base, exponential |
| Ollama | `requests.post` | 28 req/min | 1 | none |

Separation of concerns: a dedicated `GROQ_KEYWORDS_MODEL` handles keyword/role extraction (e.g. `openai/gpt-oss-20b`) while scoring uses `GROQ_MODEL` (e.g. `qwen/qwen3.6-27b`). All providers low temperature, non-streaming.

**Token bucket rate limiter:** Thread-safe, adaptive, per-provider capacity/refill.

#### Prompts (`backend/llm/prompts.py`, 260 lines)

| Prompt | Purpose |
|--------|---------|
| `relevance_prompt()` | Standard job scoring |
| `internship_relevance_prompt()` | Internship scoring (stricter, worked examples) |
| `batch_relevance_prompt()` | Batch scoring (multiple jobs per call) |
| `keywords_prompt()` | Resume → keyword/role extraction |
| `cover_letter_prompt()` | Cover letter generation |
| `referral_score_prompt()` | Referral match scoring |

**Smart truncation (`_extract_relevant`):** splits job descriptions on double newlines, scores paragraphs by keyword hits against 30+ section headers, keeps the highest-scoring text up to `max_chars`.

---

### Match Engine

**File:** `backend/match_engine/relevance_engine.py` (319 lines)

**Main entry: `filter_jobs()`** pipeline:
1. **Pre-filter:** `keyword_score` (+10 per matched keyword) + `role_match_count` (title overlap)
2. **Select candidates:** sort by role match > company user count > keyword score, take top N (20 normal, 40 internship)
3. **Batch:** batches of 5 (normal) or 2 (internship), scored concurrently via `ThreadPoolExecutor(max_workers=3)`, 90s timeout
4. **Combine:** `total_score = AI_score × 0.7 + keyword_score × 0.3`
5. **Post-process:** hallucination detection (verify matched skills against JD text), internship YOE rejection (≥3y), zero-match override
6. **Return:** sorted by `total_score` descending

**Cancellation:** every function checks `cancel_check()` at entry and during backoff sleeps.

---

### Utilities

| File | Lines | Purpose |
|------|-------|---------|
| `client_ip.py` | 16 | Client IP extraction (X-Forwarded-For aware, for rate-limiting) |
| `delay.py` | 7 | Random sleep for anti-detection |
| `experience_level.py` | 203 | Job level classification (intern/entry/senior) via regex + YOE parsing |
| `json_parser.py` | 23 | `extract_json()` — strips markdown fences, parses LLM JSON |
| `jwt.py` | 74 | Token create/decode + startup `ensure_secret` (HS256, stdlib only) |
| `logger.py` | 13 | File + console logging |
| `pii.py` | 133 | PII scrubbing/redaction helpers |
| `rate_limiter.py` | 28 | In-memory per-key rate limiter |
| `smtp_sender.py` | 87 | SMTP sending (OTP codes, invites, reports) |
| `visitor_log.py` | 17 | Visit logging helpers |

---

### Scheduler & Job Cache

**File:** `backend/scheduler.py` — runs in the API process (started/stopped in `lifespan`).

- Fills `job_cache` ahead of demand from the `prewarm_queue` grid: **30+ curated roles × all states of `in`/`us`/`ie`/`ae` × boards × both modes**, capped per run by `PREWARM_MAX_COMBOS_PER_RUN`, respecting per-board concurrency caps.
- Merges custom roles (DB) and user-searched combos (`custom_prewarm`) so they also get prewarmed.
- DB-backed leader lock (`scheduler_lock`) keeps only one process prewarming when multiple share the same DB.
- `SCHEDULER_ENABLED` (default `False`), interval `SCHEDULER_INTERVAL_MINUTES` (180).
- User searches touch `custom_prewarm` so popular combos are re-prewarmed; `gc_job_cache` prunes stale/oversized entries.

---

## Frontend

### Pages

| Page | File | Lines | Route | Purpose |
|------|------|-------|-------|---------|
| Landing | `landing.html` | 572 | `/` | Public landing — value prop, stats, login CTA |
| Search | `index.html` | 596 | `/app` | Resume upload, keyword extraction, role/location selection, job board toggles, search + results, auth modal, referral modal |
| Profile | `profile.html` | 479 | `/profile` | Profile card, saved job tracker with status management, referral network management |
| Admin | `admin.html` | 692 | `/admin` | Session analytics, charts (Chart.js), registrations, visit tracking, cache/prewarm stats, DB management |
| Terms | `terms.html` | — | `/terms.html` | Terms of service |

**Design system:** Tailwind CSS (CDN) + custom CSS. Glassmorphism header, pill toggles, skeleton loading, splash screen, fade-up animations, Jakarta Sans font. Teal color theme in internship mode.

---

### JavaScript Modules

| Module | Lines | Purpose |
|--------|-------|---------|
| `search.js` | 2297 | **Core.** Complete search workflow: state, auth flow, resume upload, keyword extraction, role/location selection, execution, polling, incremental results, job cards, save/unsave, filters, sorting, vote system, visit tracking |
| `referrals.js` | 1060 | Referral system: company discovery, request modal, dashboard (incoming/sent/accepted/declined), accept/decline/confirm/withdraw, invite flow, resume prefill, score badge, notification polling (30s, skips when logged out) |
| `admin.js` | 985 | Admin dashboard: stats, Chart.js charts, session tables, score histogram, visits, DB restore/merge, cache-stats, custom prewarm management |
| `api.js` | 82 | `window.api()` — Bearer header, JSON, toast on error, 401 → clear token + `ja:auth-required`; `window.downloadAuthed()`; cached get for public endpoints |
| `auth.js` | 577 | OTP modal, EmailJS/SMTP code flow, token session storage (`setAuthSession`), login gate debounced 60s, logout |
| `profile.js` | 363 | Profile: load/render, edit mode, resume upload, dashboard tabs |
| `jobs.js` | 201 | Saved job tracker: load, render, filter, update status, delete |
| `main.js` | 66 | Profile page entry: logout, stats bar, init |
| `utils.js` | 145 | Profile state (sessionStorage), toast, HTML escaping, date formatting |
| `terms.js` | 129 | Terms page behavior |
| `constants.js` | 37 | DEV_MODE, referral cooldown, EmailJS creds, employment labels, monthly limits |

**Module system:** `index.html` loads `search.js` as a classic script; the rest are ES modules. Cross-module communication via `window` globals (`window.api`, `window.setAuthSession`, `window.downloadAuthed`).

**API pattern:** all network calls through `window.api()` (adds the Bearer token + error handling) or direct `fetch` for public endpoints/beacons. 3s polling for search. 30s polling for referral notifications.

---

## Infrastructure

### Docker

**Two Dockerfiles:**

1. **Root `Dockerfile`** (HuggingFace Spaces): Python 3.11-slim, Chromium + deps, port 7860, copies `config.example.py` if `config.py` missing
2. **`backend/Dockerfile`** (Render): Python 3.11-slim, Chromium + deps, port 8000, expects `config.py` to exist

Both install Chromium, Playwright, Python requirements.

### Production Deployment

| Platform | Notes |
|----------|-------|
| **Oracle Cloud VM (current live prod)** | Docker container, nginx reverse proxy + Let's Encrypt HTTPS, backend on 7860, frontend served by FastAPI at `/`. Deploy/rollback flow in **`docs/deployment/jwt_deploy_runbook.md`** |
| Render | `render.yaml` — Docker service, env vars for API keys (port via `$PORT`) |
| HuggingFace Spaces | Root `Dockerfile` — port 7860 |

**Production caveats (important):**
- `backend/config.py` is **gitignored and untracked**; the **server copy is the source of truth**. Deploys must merge the config into the container; never ship the local one blindly.
- `JWT_SECRET` is baked into `config.py` on the server (with env override). Token validity survives restarts (plain `docker restart`, no `docker run -e` needed, no container recreate).
- `JWT_ALLOW_DEV_SECRET` must be **unset/0** in production so `/docs` stays admin-only and the dev code path stays off.

### Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `LLM_PROVIDER` | Primary LLM provider | `groq` |
| `GROQ_API_KEY` | Groq API key | — (hardcoded fallback) |
| `GROQ_MODEL` | Scoring model | `qwen/qwen3.6-27b` |
| `GROQ_KEYWORDS_MODEL` | Keyword/role extraction model | `openai/gpt-oss-20b` |
| `OLLAMA_MODEL` / `OLLAMA_API_URL` | Local fallback | `llama3.1:8b` / `http://localhost:11434/...` |
| `ADZUNA_APP_ID` / `ADZUNA_KEY` | Adzuna API credentials | — |
| `EMAIL_HOST/PORT/USER/PASSWORD/TO` | SMTP (OTP codes, reports) | Gmail defaults |
| `SENDER_EMAIL` | Sender for emails | — |
| `DB_BACKUP_EMAIL` | Receives DB backups | — |
| `JWT_SECRET` | JWT signing secret (overrides config) | hardcoded in config.py |
| `JWT_ALLOW_DEV_SECRET` | `"1"` enables dev secret + open docs | `""` |
| `JWT_ACCESS_TOKEN_MINUTES` | Token lifetime | `1440` |
| `ADMIN_EMAIL` | Admin identity for admin-class routes | `ammarfitwalla@gmail.com` |

---

## Configuration

**File:** `backend/config.py` (gitignored — server copy authoritative; copy from `config.example.py`)

Key settings:
- `LLM_PROVIDER`: `"groq"` | `"ollama"`
- `JWT_SECRET` / `JWT_ALLOW_DEV_SECRET` / `JWT_ACCESS_TOKEN_MINUTES` / `ADMIN_EMAIL` — JWT auth (see [Auth & Security](#auth--security-jwt))
- `ROLES_BY_CATEGORY`: 12 categories with 120+ job titles; `TARGET_ROLES` auto-flattened
- `CACHE_*`: job-cache TTL (`CACHE_TTL_HOURS` 12), min volume, prewarm limits, max entries, roles/countries (`in/us/ie/ae`)/states/cities grids
- `PREWARM_WORKERS` (7), `MAX_CONCURRENT_PER_BOARD`, `PREWARM_DELAY_SECONDS`, `PREWARM_MAX_COMBOS_PER_RUN`, `NAUKRI_USE_PROXY`
- `SCHEDULER_ENABLED` (False) / `SCHEDULER_INTERVAL_MINUTES` (180)
- `KEYWORDS_EXCLUDE` / `INTERNSHIP_KEYWORDS`
- `SCRAPE_LIMIT`: 1000 jobs max per scrape
- `COMPANIES`: curated companies for the referral marketplace
- `AUTO_APPLY`: disabled by default
- `EMAIL_*` SMTP, `GOOGLE_SHEET_NAME`, `DAILY_EMAIL_SUBJECT`

---

## API Reference

### Auth / Session

| Method | Endpoint | Auth | Body | Response |
|--------|----------|------|------|----------|
| POST | `/api/auth/send-code` | 🔓 | `{email}` | `{ok, message}` |
| POST | `/api/auth/verify-code` | 🔓 | `{email, code}` | `{ok, token, user: {email, name, referral_credits,...}}` — **token = JWT** |
| POST | `/api/auth/register` | 🔐 | `{name, company, position, linkedin_url, search_id, invited_by}` (email from token) | `{ok, user}` |
| GET | `/api/auth/companies` | 🔓 | — | `{companies: [...]}` |
| POST | `/api/auth/companies` | 🔐 | `{name}` | `{ok, company}` |

All protected endpoints require `Authorization: Bearer <token>`.

### Core Search Flow

| Method | Endpoint | Body/Params | Response |
|--------|----------|-------------|----------|
| POST | `/scrape` | `ScrapeRequest` (sites, keywords, resume_text, roles, location, internship_mode, search_id) | `{message, status, cached?}` — may be served from cache |
| GET | `/scrape/status` | `?search_id=` | `{status, pass_num, max_passes, queue_position, elapsed, logs}` |
| POST | `/scrape/stop` | `?search_id=` | `{message, status: "done"}` |
| GET | `/jobs` | `?search_id=&min_score=&site=&experience_level=&sort=` | `{total, jobs: [...]}` |
| POST | `/jobs/check-relevance` | `{job}` | relevance hint |
| GET | `/roles`, `/states` | — | role/state data |

### Profile & Saved Jobs (all 🔐)

| Method | Endpoint | Body/Params | Response |
|--------|----------|-------------|----------|
| GET | `/api/profile` | — | `{email, name, company, position, ... , saved_counts}` |
| PUT | `/api/profile` | `{name, company, position, linkedin_url}` | `{ok, user}` |
| PUT | `/api/profile/name` | `{name}` | `{ok}` |
| PUT | `/api/profile/refer-opt-in` | `{value}` | `{ok}` |
| POST | `/api/profile/resume` | `multipart file` | `{ok}` |
| GET | `/api/profile/resume` | — | file stream |
| GET | `/api/profile/resume/text` | — | `{text}` |
| POST | `/api/saved-jobs` | `{title, company, url, ...}` | `{id, saved: true}` |
| GET | `/api/saved-jobs` | `?status=` | `{jobs: [...]}` |
| POST | `/api/saved-jobs/batch-check` | `{urls: [...]}` | `{results}` |
| PATCH | `/api/saved-jobs/{job_id}/status` | `{status}` | `{ok}` |
| DELETE | `/api/saved-jobs/{job_id}` | — | `{deleted: true}` |

No `email` params anywhere — identity always comes from the token.

### Referrals

| Method | Endpoint | Auth | Body/Params | Response |
|--------|----------|------|-------------|----------|
| POST | `/api/referrals/request` | 🔐 | `{to_email, job_url, job_title, company, match_score, message}` | `{ok, id, remaining}` |
| POST | `/api/referrals/score` | 🔐 | `{job_title, company, job_description, resume_text}` | `{ok, score}` |
| POST | `/api/referrals/notify` | 🔐 | `{company}` | `{ok}` |
| POST | `/api/referrals/invite` | 🔐 | `{email}` | `{ok}` |
| POST | `/api/referrals/resolve-url` | 🔓 | `{url}` | `{company, ...}` |
| GET | `/api/referrals/incoming` | 🔐 | — | `{requests: [...]}` |
| GET | `/api/referrals/outgoing` | 🔐 | — | `{requests: [...]}` |
| GET | `/api/referrals/remaining` | 🔐 | — | `{remaining}` |
| GET | `/api/referrals/notifies` | 👑 | — | `{notifies: [...]}` |
| GET | `/api/referrals/resume` | 🔐 | — | `{text}` |
| PUT | `/api/referrals/{id}/accept` | 🔐 | — | `{ok, contact}` |
| PUT | `/api/referrals/{id}/decline` | 🔐 | — | `{ok}` |
| PUT | `/api/referrals/{id}/complete` | 🔐 | — | `{ok, credits_awarded, receiver_confirmed, sender_confirmed}` |
| PUT | `/api/referrals/{id}/confirm` | 🔐 | — | `{ok, credits_awarded, ...}` |
| PUT | `/api/referrals/{id}/withdraw` | 🔐 | — | `{ok}` |

### Admin (all 👑)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/admin/stats, /sessions, /sessions/{sid}, /sessions/{sid}/resume, /scores, /registrations, /visits, /leads, /server` | Dashboard data |
| GET | `/api/admin/db/info` | DB size/table info |
| POST | `/api/admin/db/restore, /db/merge` | Restore or merge an uploaded DB |
| GET | `/api/admin/prewarm/custom, /usage, /cache-stats` | Prewarm + cache diagnostics |
| DELETE | `/api/admin/prewarm/custom` | Remove a custom prewarm combo |
| POST | `/api/admin/users` / PATCH `/users/{email}` | Admin user management |
| GET | `/db`, `/logs` | Legacy admin — DB download / visit log (admin-guarded) |

---

## Data Flow

### Search → Score → Display (cache-first)

```
User ─POST /scrape─→ scrape.py
                        │
                        ├── Resolve location → combos (city, state) per site
                        ├── _cache_lookup(combo) ──► HIT? job_cache ──► instant jobs
                        │                              MISS ► live scrape
                        ├── Spawns background thread per combo (concurrency-capped)
                        │       ├── importlib → scraper.scrape_<site>(roles, ...)
                        │       │     └── [{title, company, url, description, tags}]
                        │       ├── Aggregate raw jobs → set_raw_jobs
                        │       ├── relevance_engine.filter_jobs(jobs, keywords, resume)
                        │       │     ├── Pre-filter: keyword_score + role_match
                        │       │     ├── Batch (5/2) → LLM batch scoring (3 workers)
                        │       │     ├── total = AI×0.7 + KW×0.3, min_score filter
                        │       │     └── results + cache save for future hits
                        │       └── Stream results to jobs table
                        └── Frontend polls /scrape/status every 3s
                              └── GET /jobs → renders job cards
```

### JWT Authenticated Actions

```
1. Click save/bookmark/referral → login modal (if no token)
2. GET /api/auth/companies (public) → company dropdown
3. POST /api/auth/send-code → email/SMTP delivers 6-digit code
4. POST /api/auth/verify-code → returns {token, user}
5. window.setAuthSession(token, email) → sessionStorage (ja_token / ja_token_email)
6. window.api(path, opts) → adds Authorization: Bearer <token>
7. auth_guard middleware: whitelist → pass; protected → 401 w/o valid token;
   admin class → 401/403 unless token email == ADMIN_EMAIL
8. POST /api/saved-jobs (token-scoped) → saved
9. Referral: POST /api/referrals/request → receiver accepts → contact revealed →
   dual-confirm within 48h → 10 credits
10. Token expires after JWT_ACCESS_TOKEN_MINUTES (24h) → 401 → token cleared →
    login modal re-shown (debounced 60s)
```

### Database Schema (Entity Relationships)

```
users (email PK)
  ├── saved_jobs (user_email FK, UNIQUE user_email+url)
  ├── saved_searches (email FK)
  ├── verification_codes (email)
  ├── referral_requests (from_email / to_email FK)
  ├── referral_scores (from_email + job_url + resume_hash)
  ├── custom_companies / custom_roles
  └── referral_notifies (admin inbox)

sessions (id PK)
  ├── jobs (session_id FK)
  └── events (session_id FK)

job_cache (role + site + location + mode)         ← filled by scheduler.py
prewarm_queue / custom_prewarm / scheduler_lock   ← scheduler bookkeeping

leads (standalone)    visits (standalone)
```
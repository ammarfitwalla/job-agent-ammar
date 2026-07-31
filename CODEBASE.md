# Codebase Documentation — Job Agent

> Automated job scraper + AI scoring + referral marketplace + web dashboard.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Project Structure](#project-structure)
3. [Backend](#backend)
   - [FastAPI Entry Point](#fastapi-entry-point)
   - [Database Layer](#database-layer)
   - [API Routes](#api-routes)
   - [Scrapers](#scrapers)
   - [LLM Integration](#llm-integration)
    - [Match Engine](#match-engine)
    - [Utilities](#utilities)
 4. [Frontend](#frontend)
   - [Pages](#pages)
   - [JavaScript Modules](#javascript-modules)
5. [Infrastructure](#infrastructure)
6. [Configuration](#configuration)
7. [API Reference](#api-reference)
8. [Data Flow](#data-flow)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        FRONTEND                                 │
│   index.html    profile.html    admin.html                      │
│   search.js     profile.js      admin.js                        │
│   auth.js       jobs.js         referrals.js                    │
│   utils.js      constants.js                                    │
├─────────────────────────────────────────────────────────────────┤
│                    FastAPI (api/main.py)                         │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────┐   │
│  │ Scrape   │ │ Jobs     │ │ Auth     │ │ Profile/Saved    │   │
│  │ Routes   │ │ Routes   │ │ Routes   │ │ Referral Routes  │   │
│  └────┬─────┘ └────┬─────┘ └──────────┘ └──────────────────┘   │
│       │             │                                           │
│  ┌────▼─────┐ ┌─────▼────┐                                     │
│  │ Scrapers │ │ Match    │                                     │
│  │ (8 sites)│ │ Engine   │                                     │
│  └────┬─────┘ └─────┬────┘                                     │
│       │             │                                           │
│  ┌────▼─────────────▼────┐   ┌──────────┐   ┌──────────────┐   │
│  │    LLM Client          │   │ Database │   │ Utils        │   │
│  │ Cerebras → Groq → Oll  │   │ (SQLite) │   │ Email,Delay  │   │
│  └───────────────────────┘   └──────────┘   └──────────────┘   │
├─────────────────────────────────────────────────────────────────┤
│                     SQLite (job_agent.db)                        │
└─────────────────────────────────────────────────────────────────┘
```

**Request lifecycle:**
1. User uploads resume + selects roles → `POST /scrape`
2. Backend scrapes job boards in a background thread
3. Raw jobs are pre-filtered by keyword score + role match
4. Top candidates are scored by LLM (AI score) and combined with keyword score
5. Results are streamed incrementally to the database
6. Frontend polls `GET /scrape/status` every 3 seconds and renders results

---

## Project Structure

```
job-agent-ammar/
├── backend/
│   ├── api/
│   │   ├── main.py              # FastAPI app, CORS, router registration, startup
│   │   ├── schemas.py           # Pydantic models (Job, ScrapeRequest, etc.)
│   │   └── routes/
│   │       ├── admin.py         # Admin dashboard data, DB restore/merge
│   │       ├── auth.py          # Email OTP auth, registration, companies
│   │       ├── email.py         # Send job report emails
│   │       ├── events.py        # Client-side event logging
│   │       ├── jobs.py          # Read scored jobs for a session
│   │       ├── leads.py         # Lead capture
│   │       ├── profile.py       # User profile CRUD, resume upload
│   │       ├── referrals.py     # Referral request/accept/decline/confirm
│   │       ├── resume.py        # Resume upload, keyword extraction, ZIP download
│   │       ├── roles.py         # Job role categories
│   │       ├── saved_jobs.py    # Saved jobs CRUD
│   │       ├── scrape.py        # Scrape orchestrator (core)
│   │       ├── states.py        # Country/state data for location autocomplete
│   │       ├── stats.py         # Public stats (searches, jobs, matches)
│   │       ├── users.py         # Company user discovery
│   │       └── visits.py        # Visit tracking (start/ping/end)
│   ├── llm/
│   │   ├── llm_client.py        # Unified LLM dispatcher with fallback chain
│   │   ├── prompts.py           # All prompt templates (scoring, cover letters)
│   │   └── providers.py         # Cerebras, Groq, Ollama provider implementations
│   ├── match_engine/
│   │   ├── relevance_engine.py  # Core scoring: keyword + AI, filtering, batching
│   │   └── resume_data.py       # Loads resume.txt at import time
│   ├── scrapers/
│   │   ├── adzuna_scraper.py    # Adzuna API (25 countries)
│   │   ├── eurojobs_scraper.py  # EuroJobs (browser scraping)
│   │   ├── gulftalent_scraper.py# GulfTalent (browser scraping)
│   │   ├── indeed_scraper.py    # Indeed via JobSpy
│   │   ├── linkedin_scraper.py  # LinkedIn HTTP + fallback Playwright
│   │   ├── linkedin_scraper_playwright.py # LinkedIn via JobSpy (fallback)
│   │   ├── naukri_scraper.py    # Naukri.com (browser scraping)
│   │   ├── remoteok_scraper.py  # RemoteOK JSON API
│   │   └── weworkremotely_scraper.py # WeWorkRemotely (browser scraping)
│   ├── auto_apply/
│   │   ├── base_apply.py        # Auto-apply base class
│   │   └── remoteok_apply.py    # RemoteOK auto-apply
│   ├── utils/
│   │   ├── delay.py             # Random sleep (anti-detection)
│   │   ├── emailer.py           # Brevo SMTP email sending
│   │   ├── experience_level.py  # Job level detection (intern/entry/senior)
│   │   ├── json_parser.py       # Extract JSON from LLM responses
│   │   ├── logger.py            # File + console logging
│   │   ├── rate_limiter.py      # In-memory rate limiter
│   │   └── visitor_log.py       # Visit logging helpers
│   ├── emails/
│   │   └── daily_report.py      # Daily email report
│   ├── sheets/
│   │   └── sheets_writer.py     # Google Sheets integration
│   ├── tests/
│   │   ├── test_features.py     # Feature tests
│   │   └── test_integration.py  # Integration tests
│   ├── db.py                    # SQLite database layer (all tables + CRUD)
│   ├── config.py                # Runtime config (gitignored)
│   ├── config.example.py        # Config template
│   ├── main.py                  # CLI orchestrator (non-API mode)
│   ├── browser.py               # Undetected-chromedriver helper
│   ├── requirements.txt         # Python dependencies
│   └── Dockerfile               # Production Docker build
├── frontend/
│   ├── index.html               # Main search page
│   ├── profile.html             # User dashboard (saved jobs + referrals)
│   ├── admin.html               # Admin analytics dashboard
│   ├── style.css                # Global stylesheet
│   └── js/
│       ├── constants.js         # Shared config (DEV_MODE, limits, EmailJS)
│       ├── utils.js             # Profile state, toast, HTML escaping
│       ├── auth.js              # Email OTP auth (profile page)
│       ├── search.js            # Core search UI (1738 lines, largest file)
│       ├── jobs.js              # Saved job tracker (profile page)
│       ├── profile.js           # Profile management
│       ├── referrals.js         # Referral system UI
│       ├── admin.js             # Admin dashboard logic
│       └── main.js              # Profile page entry point
├── resumes/                     # Uploaded resume files (gitignored)
├── Dockerfile                   # HuggingFace Spaces build
├── render.yaml                  # Render.com deployment config
├── HOW_IT_WORKS.md              # User-facing scoring explanation
├── PLAN.md                      # Profile + Saved Jobs implementation plan
├── REFERRAL_MARKETPLACE.md      # Referral marketplace implementation plan
└── votes.json                   # Community vote counter
```

---

## Backend

### FastAPI Entry Point

**File:** `backend/api/main.py` (135 lines)

- Creates the FastAPI app with CORS (`allow_origins=["*"]`)
- Registers 16 route routers on startup
- Initializes the database (`db.init_db()`)
- Serves the frontend as static files (catch-all mount at `/`)
- Provides vote counter endpoints (`/votes`, `/vote`) backed by `votes.json`
- Admin routes: `/admin` (serves admin.html), `/db` (downloads database), `/logs` (visit table)
- Health check at `/health`

**Startup sequence:**
1. `init_db()` — creates/migrates all tables

---

### Database Layer

**File:** `backend/db.py` (1061 lines)

SQLite database with WAL mode, busy timeout (5s), and a global write lock (`threading.Lock`).

**Tables (10):**

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `sessions` | Search sessions | `id`, `status`, `internship_mode`, `pass_num`, `max_passes`, `sites`, `keywords`, `roles`, `location` |
| `jobs` | Scored job listings | `session_id`, `title`, `company`, `url`, `ai_score`, `keyword_score`, `total_score`, `reason`, `is_raw` |
| `events` | Session event log | `session_id`, `event`, `data`, `elapsed_seconds` |
| `leads` | Captured leads | `email`, `name`, `roles`, `resume_snippet`, `source` |
| `users` | Registered users | `email` (PK), `name`, `company`, `position`, `linkedin_url`, `resume_filename`, `referral_credits` |
| `verification_codes` | OTP codes | `email`, `code`, `expires_at`, `used` |
| `visits` | Page visit tracking | `visit_id`, `ip_address`, `user_agent`, `device_type`, `duration_seconds`, `country`, `city` |
| `saved_jobs` | User-saved jobs | `user_email`, `title`, `company`, `url`, `application_status`, UNIQUE(`user_email`, `url`) |
| `saved_searches` | Saved search configs | `email`, `sites`, `keywords`, `roles`, `location`, `interval_hours` |
| `referral_requests` | Referral requests | `from_email`, `to_email`, `job_url`, `status`, `credit_awarded`, `receiver_confirmed`, `sender_confirmed` |
| `custom_companies` | User-added companies | `name` (UNIQUE) |

**Key DB functions (grouped by domain):**

| Domain | Functions |
|--------|-----------|
| Sessions | `create_session()`, `update_session()`, `get_session()`, `gc_sessions()` |
| Jobs | `set_filtered_jobs()`, `add_filtered_job()`, `get_filtered_jobs()`, `count_filtered_jobs()` |
| Events | `add_event()`, `get_events()` |
| Leads | `add_lead()`, `get_leads()` |
| Users | `get_user()`, `get_all_users()`, `create_user()`, `update_user_name()`, `update_user_profile()`, `get_users_by_company()`, `get_company_user_counts()` |
| Auth | `save_verification_code()`, `verify_code()` |
| Saved Jobs | `add_saved_job()`, `is_job_saved()`, `batch_check_saved()`, `get_saved_jobs()`, `update_saved_job_status()`, `delete_saved_job()`, `get_saved_jobs_status_counts()` |
| Saved Searches | `add_saved_search()`, `get_saved_searches()`, `delete_saved_search()` |
| Referrals | `create_referral_request()`, `get_incoming_referrals()`, `get_outgoing_referrals()`, `update_referral_status()`, `confirm_referral()`, `get_pending_referral()`, `get_monthly_sent_count()` |
| Companies | `add_custom_company()`, `batch_add_custom_companies()`, `get_custom_companies()` |
| Visits | `log_visit_start()`, `update_visit_ping()`, `finalize_visit()`, `get_visit_stats()`, `get_visits()` |
| Geolocation | `_resolve_ip_sync()` — IP → country/city/region via ip-api.com with 24h cache |

**Migration strategy:** The `init_db()` function runs `ALTER TABLE ... ADD COLUMN` inside try/except blocks to gracefully add new columns to existing tables without crashing.

---

### API Routes

#### Scrape Routes (`/scrape`)

**File:** `backend/api/routes/scrape.py` (432 lines) — the core orchestrator.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/scrape` | POST | Starts a background scrape thread. Accepts `ScrapeRequest` (sites, keywords, resume_text, roles, location, internship_mode, etc.) |
| `/scrape/stop` | POST | Cancels a running scrape by setting `cancel=1` in the session |
| `/scrape/status` | GET | Polls progress: status, pass number, queue position, elapsed time, log messages |

**Scrape pipeline (`run_scrape`):**
1. Create session in DB
2. Save resume text to temp file
3. Dispatch to `_scrape_normal()` or `_scrape_internship()` based on mode
4. Normal mode: single pass across all selected sites → score → done
5. Internship mode: multi-pass loop (up to `max_passes`), filtering for entry-level roles, stops when enough relevant results found

**Dynamic scraper loading:** Uses `importlib` to load scraper modules at runtime based on `SITE_MAP`:
```python
SITE_MAP = {
    "remoteok": ("scrapers.remoteok_scraper", "scrape_remoteok"),
    "adzuna": ("scrapers.adzuna_scraper", "scrape_adzuna"),
    "indeed": ("scrapers.indeed_scraper", "scrape_indeed"),
    "linkedin": ("scrapers.linkedin_scraper", "scrape_linkedin"),
    "weworkremotely": ("scrapers.weworkremotely_scraper", "scrape_wwr"),
    "naukri": ("scrapers.naukri_scraper", "scrape_naukri"),
    "gulftalent": ("scrapers.gulftalent_scraper", "scrape_gulftalent"),
    "eurojobs": ("scrapers.eurojobs_scraper", "scrape_eurojobs"),
}
```

**Stale session cleanup:** A daemon thread runs every 60s, cancelling sessions running longer than 15 minutes.

**Company harvesting:** After scoring, new company names are extracted and persisted to `custom_companies`.

---

#### Auth Routes (`/api/auth`)

**File:** `backend/api/routes/auth.py` (122 lines)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/auth/send-code` | POST | Generates 6-digit OTP, stores in DB with 10min expiry. Rate-limited: 3 requests/minute per email |
| `/api/auth/verify-code` | POST | Verifies OTP, creates user if new, returns user profile. Rate-limited: 5 attempts/5min |
| `/api/auth/register` | POST | Creates/updates user with employment info (name, company, position, LinkedIn) |
| `/api/auth/companies` | GET | Returns merged list of curated + custom companies |
| `/api/auth/companies` | POST | Adds a new custom company name |

**DEV_MODE:** When enabled, `/send-code` returns `"123456"` without sending email, and `/verify-code` accepts `"123456"` as the code.

**Resume association:** On registration, if a `search_id` is provided, the search's resume file is copied to the user's profile.

---

#### Profile Routes (`/api/profile`)

**File:** `backend/api/routes/profile.py` (93 lines)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/profile` | GET | Returns user profile with saved job status counts |
| `/api/profile` | PUT | Updates profile fields (name, company, position, LinkedIn) |
| `/api/profile/name` | PUT | Updates name only |
| `/api/profile/resume` | POST | Uploads resume file (PDF/DOCX/TXT), associates with user |
| `/api/profile/resume` | GET | Downloads user's uploaded resume |

---

#### Saved Jobs Routes (`/api/saved-jobs`)

**File:** `backend/api/routes/saved_jobs.py` (73 lines)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/saved-jobs` | POST | Saves a job to user's profile |
| `/api/saved-jobs` | GET | Lists saved jobs (optional `status` filter) |
| `/api/saved-jobs/check` | GET | Checks if a specific URL is saved |
| `/api/saved-jobs/batch-check` | POST | Checks multiple URLs at once |
| `/api/saved-jobs/{id}/status` | PATCH | Updates application status (saved/applied/interviewing/offer/rejected) |
| `/api/saved-jobs/{id}` | DELETE | Removes saved job |

**Constraint:** UNIQUE(`user_email`, `url`) — prevents duplicate saves.

---

#### Referral Routes (`/api/referrals`)

**File:** `backend/api/routes/referrals.py` (163 lines)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/referrals/request` | POST | Send referral request. Rate-limited (10/min), monthly limit (5), duplicate check |
| `/api/referrals/incoming` | GET | Requests sent to the user (with sender profile enrichment) |
| `/api/referrals/outgoing` | GET | Requests sent by the user (with receiver profile enrichment) |
| `/api/referrals/{id}/accept` | PUT | Accept request → reveals requester's contact info |
| `/api/referrals/{id}/decline` | PUT | Decline request |
| `/api/referrals/{id}/complete` | PUT | Receiver confirms referral (part of dual-confirmation) |
| `/api/referrals/{id}/confirm` | PUT | Sender confirms referral (part of dual-confirmation) |
| `/api/referrals/{id}/withdraw` | PUT | Cancel pending outgoing request |
| `/api/referrals/remaining` | GET | Returns remaining monthly request count |

**Dual-confirmation system:** Both referrer and requester must confirm within 48 hours of acceptance. When both confirm, 10 credits are awarded to the referrer.

---

#### Other Routes

| File | Prefix | Endpoints |
|------|--------|-----------|
| `jobs.py` | `/jobs` | `GET /jobs` (list scored jobs for session), `GET /jobs/{index}` (single job) |
| `email.py` | `/email` | `POST /email/report` (send job batch email) |
| `resume.py` | `/resume` | `POST /resume/upload`, `GET /resume/download` (ZIP), `DELETE /resume/storage`, `POST /resume/keywords` (LLM extraction) |
| `roles.py` | `/roles` | `GET /roles` (returns categorized role lists) |
| `states.py` | `/states` | `GET /states` (country/state data with caching) |
| `events.py` | `/api/events` | `POST /api/events` (log client events) |
| `leads.py` | `/api` | `POST /api/lead`, `GET /api/leads` |
| `visits.py` | `/api/visit` | `POST /api/visit/start`, `POST /api/visit/ping`, `POST /api/visit/end` |
| `users.py` | `/api/users` | `GET /api/users/at-company`, `GET /api/users/company-counts` |
| `stats.py` | `/api/stats` | `GET /api/stats/public` (searches, jobs, matches counts) |
| `admin.py` | `/api/admin` | Stats, sessions, session detail, scores, registrations, visits, leads, DB restore/merge, resume upload |

---

### Scrapers

8 job board scrapers, all returning a standardized list of dicts with keys: `title`, `company`, `location`, `url`, `description`, `tags`, `salary`.

| Scraper | Site | Method | Lines | Notes |
|---------|------|--------|-------|-------|
| `remoteok_scraper.py` | RemoteOK | JSON API (`/api`) | 109 | Fuzzy role matching, paginated (5 pages) |
| `weworkremotely_scraper.py` | WeWorkRemotely | Browser scraping | 71 | Fetches individual job pages for descriptions |
| `adzuna_scraper.py` | Adzuna | REST API | 189 | 25 countries, category-based queries, requires API keys |
| `indeed_scraper.py` | Indeed | JobSpy library | 184 | Country-specific domains, salary formatting |
| `linkedin_scraper.py` | LinkedIn | HTTP + guest API | 439 | Primary scraper; rotates user agents, fetches descriptions in parallel |
| `linkedin_scraper_playwright.py` | LinkedIn | JobSpy library | 238 | Fallback when HTTP scraper fails |
| `naukri_scraper.py` | Naukri | Browser scraping | 83 | Indian job portal, multiple CSS selectors |
| `gulftalent_scraper.py` | GulfTalent | Browser scraping | 74 | Gulf region, placeholder descriptions |
| `eurojobs_scraper.py` | EuroJobs | Browser scraping | 105 | European job portal |

**Browser scraping:** Uses `undetected-chromedriver` via `browser.py` for sites that block standard requests. Adds random delays (2-4s) between requests.

**Internship mode:** Scrapers modify search queries (append "intern", filter by tech keywords) when `internship_mode=True`.

**Role matching:** Most scrapers use fuzzy word-overlap matching (`_role_matches()`) — a job title matches a role if at least 60% of significant words overlap, with compound-word fallback.

---

### LLM Integration

#### Client (`backend/llm/llm_client.py`, 58 lines)

Unified dispatcher with fallback chain:
```
Primary Provider (configurable) → Cerebras → Groq
```

- `LLMClient.chat()` — single-job prompts (max 600 tokens)
- `LLMClient.batch_chat()` — batch prompts (max 3000 tokens)
- Falls back to next provider on empty response
- Cooperative cancellation via `cancel_check` callable

#### Providers (`backend/llm/providers.py`, 200 lines)

| Provider | Library | Rate Limit | Retries | Backoff |
|----------|---------|------------|---------|---------|
| Cerebras | `openai` (custom base_url) | 4 req/min | 3 | 10s base, exponential |
| Groq | `groq` | 28 req/min | 3 (rate limit only) | 10s base, exponential |
| Ollama | `requests.post` | 28 req/min | 1 (no retry) | N/A |

All providers: temperature 0.1-0.25, non-streaming, single user message (no system prompt).

**Token bucket rate limiter:** Thread-safe, adaptive. Cerebras capacity=4, refill=4/60 tokens per second.

**Backoff:** `min(base * 2^attempt, max_wait)` + 25% jitter. Sleep loops check `cancel_check` every 0.5s.

#### Prompts (`backend/llm/prompts.py`, 259 lines)

| Prompt | Purpose | Token Budget |
|--------|---------|-------------|
| `relevance_prompt()` | Standard job scoring | 600 |
| `internship_relevance_prompt()` | Internship scoring (stricter, 5 worked examples) | 600 |
| `batch_relevance_prompt()` | Batch scoring (multiple jobs per call) | 3000 |
| `cover_letter_prompt()` | Cover letter generation | N/A |

**Smart truncation (`_extract_relevant`):** Splits job descriptions on double newlines, scores each paragraph by keyword hits in 30+ section headers (e.g., "qualification", "what you'll do", "must have"), keeps highest-scoring paragraphs up to `max_chars`.

**Scoring rubric (standard):**
| Criteria | Points |
|----------|--------|
| Core role/domain match | +40 |
| Required tools/tech match | +20 |
| Relevant experience level | +15 |
| Secondary skills match | +10 |
| Domain mismatch | -20 |
| Completely unrelated | -40 |

---

### Match Engine

**File:** `backend/match_engine/relevance_engine.py` (296 lines)

**Main entry: `filter_jobs()`**

Pipeline:
1. **Pre-filter:** Score all jobs by `keyword_score` (+10 per matched keyword) + `role_match_count` (title word overlap)
2. **Select candidates:** Sort by role match > company user count > keyword score, take top N (20 normal, 40 internship)
3. **Batch:** Split into batches (5 normal, 2 internship per batch)
4. **LLM score:** Process batches concurrently via `ThreadPoolExecutor(max_workers=3)`, 90s timeout per batch
5. **Combine:** `total_score = AI_score × 0.7 + keyword_score × 0.3`
6. **Post-process:** Hallucination detection (verify matched skills against JD text), internship YOE rejection (≥3 years), zero-match override
7. **Return:** Sorted by `total_score` descending

**Internship mode specifics:**
- Dedicated Cerebras provider with separate API key/model/rate config
- Smaller batch sizes (2 vs 5)
- Stricter scoring: skill-count-based rubric (0 matches → 10-15, 5+ matches → 70-95)
- Rejects jobs requiring ≥3 years of experience

**Cancellation:** Every function checks `cancel_check()` at entry and during backoff sleeps. Batch futures are cancelled when detected.

---

### Utilities

| File | Lines | Purpose |
|------|-------|---------|
| `delay.py` | 7 | `delay(min, max)` — random sleep for anti-detection |
| `emailer.py` | 42 | Brevo SMTP API email sending (HTML format) |
| `experience_level.py` | 81 | Classifies jobs as `internship`, `entry_level`, or `None` using regex patterns and YOE parsing |
| `json_parser.py` | 23 | `extract_json()` — strips markdown code fences and parses JSON from LLM responses |
| `logger.py` | — | File + console logging |
| `rate_limiter.py` | — | In-memory rate limiter for API endpoints |
| `visitor_log.py` | — | Visit logging helpers |

---

## Frontend

### Pages

| Page | File | Lines | Purpose |
|------|------|-------|---------|
| Search | `index.html` | 447 | Main landing page — resume upload, keyword extraction, role selection, location, job board toggles, search execution, results display, auth modal, referral modal |
| Profile | `profile.html` | 448 | User dashboard — profile card, saved job tracker with status management, referral network management |
| Admin | `admin.html` | 389 | Admin-only — session analytics, charts (Chart.js), registration table, visit tracking, DB management |

**Design system:** Tailwind CSS (CDN) + custom CSS. Glassmorphism header, pill-based toggles, skeleton loading, splash screen, fade-up animations. Plus Jakarta Sans font. Internship mode has teal color theme.

---

### JavaScript Modules

| Module | Lines | Purpose |
|--------|-------|---------|
| `search.js` | 1738 | **Core.** Complete search workflow: state management, auth flow, resume upload, keyword extraction, role/location selection, search execution, polling, incremental results, job card rendering, save/unsave, filtering, sorting, vote system, visit tracking |
| `referrals.js` | 616 | Referral system: company user discovery, referral request modal, dashboard (incoming/sent/accepted/declined), accept/decline/confirm/withdraw, notification polling (30s) |
| `admin.js` | 575 | Admin dashboard: stats loading, Chart.js charts, session tables with expandable details, score distribution histogram, visit tracking, DB restore/merge |
| `auth.js` | 268 | Profile page auth: EmailJS integration, code send/verify, registration, company dropdown |
| `profile.js` | 339 | Profile page: load/render profile, edit mode, resume upload, dashboard tab switching |
| `jobs.js` | 184 | Saved job tracker: load, render, filter by status, update status, delete |
| `main.js` | 93 | Profile page entry: logout, stats bar, DOMContentLoaded init |
| `utils.js` | 119 | Shared: profile state (localStorage), toast notifications, HTML escaping, date formatting |
| `constants.js` | 37 | Config: DEV_MODE, referral cooldown, EmailJS credentials, employment labels, monthly limits |

**Module system:** Mixed — `index.html` loads `search.js` as classic script, others as ES modules. Cross-module communication via `window` globals.

**State management:** Vanilla JS — module-level variables + localStorage. Profile state shared via `utils.js`. Search state in `search.js`. No framework.

**API pattern:** RESTful, all prefixed with `/api/` for data and `/scrape/` for search. Beacons for fire-and-forget analytics. 3-second polling interval for search progress.

---

## Infrastructure

### Docker

**Two Dockerfiles:**

1. **Root `Dockerfile`** (HuggingFace Spaces): Python 3.11-slim, Chromium + deps, port 7860, copies `config.example.py` if `config.py` missing
2. **`backend/Dockerfile`** (Render): Python 3.11-slim, Chromium + deps, port 8000, expects `config.py` to exist

Both install: Chromium, Playwright, Python requirements, Chromium browser.

### Deployment

| Platform | Config | Port |
|----------|--------|------|
| Render | `render.yaml` — Docker service, env vars for API keys | 8000 (configurable via `$PORT`) |
| HuggingFace Spaces | Root `Dockerfile` | 7860 |

### Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `LLM_PROVIDER` | Primary LLM provider | `cerebras` |
| `CEREBRAS_API_KEY` | Cerebras API key | — |
| `CEREBRAS_MODEL` | Cerebras model | `gpt-oss-120b` |
| `INTERNSHIP_CEREBRAS_API_KEY` | Separate key for internship scoring | — |
| `GROQ_API_KEY` | Groq API key (fallback) | — |
| `GROQ_MODEL` | Groq model | `meta-llama/llama-4-scout-17b-16e-instruct` |
| `OLLAMA_MODEL` | Ollama model (local) | `llama3.1:8b` |
| `OLLAMA_API_URL` | Ollama endpoint | `http://localhost:11434/v1/chat/completions` |
| `ADZUNA_APP_ID` / `ADZUNA_KEY` | Adzuna API credentials | — |
| `EMAIL_HOST` / `EMAIL_PORT` / `EMAIL_USER` / `EMAIL_PASSWORD` / `EMAIL_TO` | SMTP email config | Gmail defaults |
| `SENDER_EMAIL` | Sender for reports | — |

---

## Configuration

**File:** `backend/config.py` (gitignored, copy from `config.example.py`)

Key settings:
- `LLM_PROVIDER`: `"cerebras"` | `"groq"` | `"ollama"`
- `ROLES_BY_CATEGORY`: 12 categories with 120+ job titles
- `TARGET_ROLES`: Flat list of all roles (auto-generated)
- `KEYWORDS_EXCLUDE`: Terms to filter out (senior manager, sales, HR, etc.)
- `INTERNSHIP_KEYWORDS`: Terms for internship mode filtering
- `SCRAPE_LIMIT`: 1000 jobs max per scrape
- `COMPANIES`: 251 curated companies for referral marketplace
- `AUTO_APPLY`: Disabled by default

---

## API Reference

### Core Search Flow

| Method | Endpoint | Body/Params | Response |
|--------|----------|-------------|----------|
| POST | `/scrape` | `ScrapeRequest` (sites, keywords, resume_text, roles, location, internship_mode, search_id, user_email) | `{message, status: "running"}` |
| GET | `/scrape/status` | `?search_id=` | `{status, pass_num, max_passes, last_scrape_raw, last_scrape_relevant, elapsed, logs}` |
| POST | `/scrape/stop` | `?search_id=` | `{message, status: "done"}` |
| GET | `/jobs` | `?search_id=&min_score=&site=&experience_level=&sort=` | `{total, jobs: [{title, company, url, ai_score, keyword_score, total_score, reason, ...}]}` |

### Authentication

| Method | Endpoint | Body | Response |
|--------|----------|------|----------|
| POST | `/api/auth/send-code` | `{email}` | `{ok, code}` |
| POST | `/api/auth/verify-code` | `{email, code}` | `{ok, user: {email, name, company, ...}}` |
| POST | `/api/auth/register` | `{email, name, company, position, linkedin_url, search_id}` | `{ok, user}` |
| GET | `/api/auth/companies` | — | `{companies: [...]}` |

### Profile & Saved Jobs

| Method | Endpoint | Body/Params | Response |
|--------|----------|-------------|----------|
| GET | `/api/profile` | `?email=` | `{email, name, company, position, ...}` |
| PUT | `/api/profile` | `{email, name, company, position, linkedin_url}` | `{ok, user}` |
| POST | `/api/saved-jobs` | `{email, title, company, url, ...}` | `{id, saved: true}` |
| GET | `/api/saved-jobs` | `?email=&status=` | `{jobs: [...]}` |
| PATCH | `/api/saved-jobs/{id}/status` | `{status}` | `{ok}` |
| DELETE | `/api/saved-jobs/{id}` | — | `{deleted: true}` |

### Referrals

| Method | Endpoint | Body/Params | Response |
|--------|----------|-------------|----------|
| POST | `/api/referrals/request` | `{from_email, to_email, job_url, job_title, company, match_score, message}` | `{ok, id, remaining}` |
| GET | `/api/referrals/incoming` | `?email=` | `{requests: [...]}` |
| GET | `/api/referrals/outgoing` | `?email=` | `{requests: [...]}` |
| PUT | `/api/referrals/{id}/accept` | `{email}` | `{ok, contact: {email, name, linkedin_url}}` |
| PUT | `/api/referrals/{id}/decline` | `{email}` | `{ok}` |
| PUT | `/api/referrals/{id}/complete` | `{email}` | `{ok, credits_awarded, receiver_confirmed, sender_confirmed}` |
| PUT | `/api/referrals/{id}/confirm` | `{email}` | `{ok, credits_awarded, ...}` |

---

## Data Flow

### Search → Score → Display

```
User ─POST /scrape─→ scrape.py
                        │
                        ├── Creates session in DB
                        ├── Spawns background thread
                        │       │
                        │       ├── For each site in [remoteok, indeed, linkedin, ...]:
                        │       │     └── importlib → scraper.scrape_<site>(roles, ...)
                        │       │           └── Returns [{title, company, url, description, tags}]
                        │       │
                        │       ├── Aggregate raw jobs
                        │       │
                        │       ├── relevance_engine.filter_jobs(jobs, keywords, resume)
                        │       │     │
                        │       │     ├── Pre-filter: keyword_score + role_match_count
                        │       │     ├── Select top 20 candidates
                        │       │     ├── Batch into groups of 5
                        │       │     ├── LLM scoring (3 concurrent workers):
                        │       │     │     │
                        │       │     │     ├── Build prompt (prompts.py)
                        │       │     │     ├── LLMClient.batch_chat(prompt)
                        │       │     │     │     └── Cerebras → Groq (fallback)
                        │       │     │     ├── Parse JSON response
                        │       │     │     └── Verify hallucinated skills
                        │       │     │
                        │       │     ├── Combine: total = AI×0.7 + KW×0.3
                        │       │     ├── Filter by min_score (50)
                        │       │     └── Return sorted results
                        │       │
                        │       └── Stream results to DB (add_filtered_job per result)
                        │
                        └── Frontend polls /scrape/status every 3s
                              └── GET /jobs → renders job cards
```

### Auth → Save Job → Referral

```
1. Click bookmark → auth modal (if not logged in)
2. Enter email → POST /api/auth/send-code → EmailJS delivers code
3. Enter code → POST /api/auth/verify-code → user created/returned
4. Profile stored in localStorage
5. POST /api/saved-jobs → job saved with status "saved"
6. On profile page: manage status (applied/interviewing/offer/rejected)
7. See company badge on job card → click → referral modal
8. POST /api/referrals/request → request sent
9. Referrer accepts → contact info revealed
10. Both confirm within 48h → 10 credits awarded
```

### Database Schema (Entity Relationships)

```
users (email PK)
  ├── saved_jobs (user_email FK, UNIQUE user_email+url)
  ├── saved_searches (email FK)
  ├── verification_codes (email)
  ├── referral_requests (from_email / to_email FK)
  └── custom_companies

sessions (id PK)
  ├── jobs (session_id FK)
  └── events (session_id FK)

leads (standalone, references session_id)
visits (standalone, references session_id)
```

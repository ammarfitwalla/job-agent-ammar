# Job Search Agent — AI-Powered Job Matcher

## Resume Summary (top-10 lifters)

1. **What it is:** A production job-search platform live for **10 users worldwide**, scraping job boards (LinkedIn, Naukri, +) nightly with **on-demand AI scoring** of any job against the user's own resume.
2. **Hybrid scoring engine:** LLM + keyword heuristics return 0–100 score, relevance flag, matched/missing skills, and plain-English rationale — with skill-aware smart JD truncation and anti-hallucination guards.
3. **Scale:** 2,000+ live postings in the SQLite pipeline; on-demand scoring **cached by resume-hash (email × job × MD5)** so repeat evaluations cost ~zero.
4. **Concurrency & resilience:** multi-threaded batch LLM scoring, streaming progress with cancellation, token-bucket LLM rate limiting, circuit-breaker + exponential-backoff on scrapers, and provider abstraction with automatic Groq→Ollama fallback.
5. **Data engineering:** idempotent schema migrations + zero-downtime online backfill of 2,000+ jobs; boundary-tuned YOE classification buckets (0-2 → 10+ yrs).
6. **Privacy by design:** PII scrubber (name, email, phone, addresses, LinkedIn/GitHub) strips personal data from every resume before any LLM call — 27 unit tests + in-container smoke verification.
7. **Full-stack & DX:** FastAPI + SQLite, vanilla-JS SPA, resume parsing (PDF/DOCX/TXT), AI keyword/role extraction, cover-letter generation, referral invites with notify-me.
8. **Deployment & observability:** Dockerized on Oracle Cloud Ubuntu; GitHub → artifact-sync → zero-downtime restart pipeline with health-check verification; nightly scheduler + prewarm; systemd + Cockpit monitoring; self-healing SMTP for 7.5 MB DB backups.
9. **ROI:** ~80% less manual screening, faster apply funnel, referrals (the top hiring channel) made trackable + automated, candidate PII protected end-to-end.
10. **Stack:** Python (FastAPI, SQLite), vanilla JS/HTML/CSS, Groq/OpenAI-compatible LLMs, Docker, Linux, systemd, Cockpit.

## System Design & Architecture

```
Job boards ─▶ Scrapers ─▶ Normalizer ─▶ SQLite pipeline ─▶ Scoring API ─▶ React-free SPA
                                                              │
               Users / sessions ──▶ resume store ──▶ PII scrubber ──▶ LLM provider (Groq, fallback: Ollama)
                                                              └──▶ score cache [email+job+resume-hash]
               Nightly scheduler + prewarm ──▶ /health monitor + SMTP backup mailer
```

**Patterns applied (with real trade-offs):**
- **Layered architecture:** `routes → match-engine → LLM providers → DB` with typed Pydantic schemas; concerns isolated, so scraper/score/schema changes never ripple across modules.
- **Provider abstraction & graceful degradation:** adapter pattern over Groq/Ollama with a fallback chain — if the primary model fails, the system silently degrades instead of breaking.
- **Multi-user isolation:** 10 live users with per-user sessions, resumes, and scoring — architected multi-tenant from day one (auth-gated referrals, per-user caches).
- **Traffic control — 3 rate-limit layers:** fixed-window API limiter (auth/OTP, referral invites, notify-me, anonymous URL-resolve; keyed by email & IP) for anti-abuse; a thread-safe **token bucket** (28 req/min) throttling LLM calls client-side to stay under quota; and jittered inter-request delays on scraper traffic to avoid bot detection.
- **Circuit breaker + exponential backoff with jitter:** per-site failure tracking trips a breaker that bails instantly instead of re-paying escalating backoff on a dead endpoint; retries use `min(base·2ⁿ, cap) + jitter`; SMTP retries on fresh connections.
- **Flow control:** thread-pooled batch LLM calls with bounded workers, plus per-board `BoundedSemaphore`s that cap concurrent scrapes per site and a common fallback lock.
- **Cancellation & progress:** a `cancel_check` callback threads through the LLM providers, letting the UI abort long scans; per-session event log streams lifecycle/timing for progress-aware rendering.
- **Caching layer — hierarchical & self-healing:** scored results memoized on `(from_email, job_url, MD5(resume))`; a write-through `job_cache` keyed on an 8-field composite serves cache-first, and every live miss **refills the very cache slot it came from**; exact-city → state → country specificity fallback; a prewarm queue back-fills combos before users need them; memory memo for job counts + IP geo.
- **Idempotency & zero-downtime migration:** versioned schema migrations (add-column, constrained table-rebuild with `INSERT OR IGNORE` data-preserving re-entry); a one-shot backfill reclassified 2,000+ rows live without dropping the service.
- **SQLite production tuning:** WAL journaling + `busy_timeout` + `synchronous=NORMAL` + periodic `wal_checkpoint(TRUNCATE)`, a single-writer lock for cross-thread writes, and a stale-lock-safe file lock for the scheduler.
- **Observability:** structured event log per session (timing + lifecycle), `/health` wired into the cron monitor, systemd + Cockpit for host/container visibility.
- **Security/privacy as design principle:** data minimization at the LLM boundary (PII redaction), no secrets in images (env-injected config), SSH-tunneled admin UI.
- **CD + ops:** file-sync deployment pipeline, restart-on-immutable-artifact, verified health after every release.

## Failures in Development & Production (and how we handled them)

- **Job-scoring boundary bug (dev):** "4–6 yrs" resumes landed in the wrong experience bucket — root-caused to a threshold asymmetry in the YOE classifier. Fixed with boundary-tuned heuristics + 10 regression tests, hot-deployed, and **live-backfilled 2,031 jobs** with zero downtime.
- **Backup emails silently failing in production:** 7–8 MB DB backups dropped mid-transfer (`SMTPServerDisconnected`) because Gmail closes the connection inside the 30 s build timeout. Rewrote the mailer with a 120 s timeout, 3 retries, and a **fresh SMTP connection per attempt**, then verified a real 7.52 MB send end-to-end.
- **LLM quota throttling (429s) & flaky providers:** solved with client-side token-bucket throttling, exponential backoff + jitter, and automatic Groq→Ollama fallback so scoring degrades gracefully instead of failing.
- **Job boards rate-limiting scrapers (LinkedIn 429 / Naukri 406):** first surfaced as intermittent empty scrapes; added a circuit breaker (bail fast after consecutive exhaustions), jittered request delays, and a health-tested proxy pool.
- **SQLite write contention & schema drift:** cross-thread writes caused "database is locked" — adopted WAL + busy_timeout + a single-writer lock, plus versioned idempotent migrations (table-rebuild for UNIQUE-constraint changes) to prevent drift.
- **Mobile UI clipping:** dropdown overflowed small viewports → viewport-aware positioning (edge clamping + flip-above) chosen over brittle pixel media queries.
- **Stale scheduler lock after crashes (^C/kill):** lock file with retry-on-stale semantics prevents double-scrape storms on recovery.

## Logs & Monitoring

- Structured **per-session event log** (lifecycle + timing) makes every user flow traceable end-to-end.
- **`/health` endpoint** polled by an external cron → failure alerts without installing agents.
- **Docker + systemd journal** and a **Cockpit GUI** (live metrics, service status, terminal, log viewer) — admin access SSH-tunneled for security.
- **Post-deploy verification is part of the pipeline:** endpoint health checks + in-container smoke tests after every release.
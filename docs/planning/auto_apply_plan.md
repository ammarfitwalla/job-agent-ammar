# Auto-Apply — Implementation Plan

> **Status:** proposed · **Date:** 2026-10-17
> **Owner:** backend
> **Decision:** **server-side submission of public, login-free application forms. No credentials stored. No LinkedIn/Naukri login bots.**
> **Scope:** this doc covers the B2C auto-apply feature for JobAwn (the monetizable "system-layer" capability).

## Goal

Let a paying user upload a resume once, then have JobAwn **discover matching jobs, tailor the application, submit it, and track it — unattended, server-side.** Sell it on a **credit model** (1 credit = 1 application), gated so only well-matched jobs are auto-applied.

## Decision & rationale

Three delivery methods were considered. The product will use **method 2, restricted to login-free forms**.

| Method | Verdict | Why |
|---|---|---|
| **1. Browser extension (user's own browser/session)** | Back-pocket, later | Safest (no credentials), works on login-walled forms — but needs the browser open and a new distribution surface (Chrome Web Store). |
| **2. Server-side automation** | ✅ **Chosen — login-free forms only** | Runs unattended ("applies while you sleep"), no credentials, no install. Restricted to **Greenhouse / Lever / Ashby / company career pages**. |
| **3. Email applications** | Supplement | Simple and safe, but from JobAwn's own domain it is cold email → deliverability + reputation risk. Secondary only. |
| ~~Server-side bots that log into user accounts~~ | ❌ Never | Requires storing platform passwords; gets users banned; the blame lands on us. |

**Why server-side wins here:** it's the only method that is both unattended *and* free of credential storage — because open ATS forms need no login. It also produces applications recorded **in the employer's own system**, which convert better than aggregator reposts.

**Hard rule:** if it needs a login, we don't automate it. That single constraint is what keeps the feature safe and honest.

## Scope

**In scope (sandboxed to public forms):**
- Greenhouse, Lever, Ashby application pages (no login).
- Company career-page forms where the form is public.
- Email applications **only** to addresses the employer published in the posting, sent from a **dedicated warmed JobAwn domain**, reply-to = the candidate.

**Out of scope (deliberately):**
- LinkedIn / Naukri Easy Apply (account bans).
- Workday account creation and multi-step login flows (revisit later, if ever).
- Any storage of job-site credentials.

## Architecture

Builds on the existing `backend/auto_apply/` stub (`base_apply.py`, `remoteok_apply.py`).

```
backend/auto_apply/
  base_apply.py         # EXTEND: headless session, field-fill, submit, screenshot
  platforms/
    registry.py         # like scrape.py SITE_MAP
    greenhouse.py       # ← first adapter
    lever.py
    ashby.py
    email_apply.py      # supplement; warmed domain, reply-to = candidate
  answers.py            # reusable answer bank (work auth, notice, salary, …)
  queue.py              # apply_queue: status, attempts, evidence, retries
  worker.py             # daemon thread (mirror scheduler.start_mail_worker)
backend/documents/
  tailor.py             # LLM resume tailoring (new prompt in llm/prompts.py)
  render.py             # HTML/CSS -> PDF via Playwright page.pdf()  (no new dep)
```

### The apply loop (every application)

1. **Fit gate** — proceed only if `total_score`/`ai_score` ≥ `AUTO_APPLY_MIN_SCORE` (start ~0.75). Keeps us out of the spam pile.
2. **Tailor** — LLM rewrites the resume for this job; generate the cover letter (already exists: `cover_letters/generator.py`).
3. **Render** — resume → PDF via Playwright `page.pdf()` (dependency already present).
4. **Submit** — the platform adapter fills fields and submits.
5. **Verify** — screenshot + confirmation URL + timestamp; record which document version was sent.
6. **Record** — flip `saved_jobs.application_status` `saved → applied`.

### Modes
- **`review` (default):** application is drafted and queued as `pending_review`; the user approves before submission.
- **`batch`:** many drafts; approve as a batch.
- **`autonomous`:** opt-in; queued for immediate submission.

## Reuse vs build

**Already present in JobAwn (reuse):**
- Playwright + `playwright-stealth` (requirements).
- Resume parsing (`PyMuPDF`, `python-docx`).
- Cover-letter generation (`backend/cover_letters/generator.py`, `llm/prompts.py:233`).
- LLM client + failover (`llm/llm_client.py`).
- Application tracking lifecycle (`saved_jobs.application_status`, `update_saved_job_status`, `PATCH /saved_jobs/{id}/status`).
- Daemon-worker pattern (`scheduler.py`: `start_mail_worker` etc.).
- Config surface (`AUTO_APPLY`, `CHROME_PROFILE_PATH` in `config.py`).
- Email send path (`utils/smtp_sender.py`, `backend/emails/`).

**To build:**
- Per-platform apply adapters (only a RemoteOK demo exists today).
- Resume **tailoring + PDF rendering** (parser exists; generator does not).
- `apply_queue` table + apply worker + modes.
- Answer bank (custom-question handling), with human review for sensitive answers.
- Submission **evidence** capture.
- Fit-gate wiring into the apply path.

## The four risks (and mitigations)

1. **CAPTCHA** (reCAPTCHA/hCaptcha occasionally embedded). → Detect, don't fight. Route those jobs to a "needs your help" queue and notify the user to click.
2. **Breakage** (forms change; selectors rot). → Per-site adapters + a success/failure-rate monitor; alert on adapter degradation; fail gracefully rather than submit garbage.
3. **Resources** (headless Chromium ≈ 200–400 MB each; shared VM with JobAwn + the sibling product). → Hard cap concurrency (start 2–3), run the apply worker **off-peak**, queue work (never a browser per request).
4. **IP / volume** (many submissions from one IP get rate-limited). → Use rotating proxies with **sticky sessions per submission** (never hop mid-form); keep volume human-paced.

## Guardrails (non-negotiable)

- **No credentials stored, ever** — login-free forms only.
- **`review` mode default**; `autonomous` is opt-in.
- **Human-in-the-loop for sensitive answers** (work authorization, salary) — never auto-answered.
- **Evidence per submission** — screenshot + final URL + resume version.
- **Dedupe** — never apply twice (existing `saved_jobs UNIQUE(user_email, url)`); retries must be idempotent (no double-submit).
- **Legal** — we act as the candidate's consented agent; the content is theirs. Review each ATS's automated-submission terms once, up front.

## Data model (new)

- `apply_queue` — `id, user_email, job_url, platform, status (pending|pending_review|submitted|failed|needs_help), attempts, last_error, evidence_path, doc_version, created_at, updated_at` with `UNIQUE(user_email, job_url)`.
- `application_answers` — `user_email, key, value` (reusable screening answers) + a per-application override store.
- `applications_log` — evidence rows: `user_email, job_url, submitted_at, final_url, screenshot_path, resume_version, mode`.

(Follow the existing `email_queue` idempotent-insert pattern.)

## Pricing tie-in

- **1 credit = 1 application.** Credits never expire (matches the category norm, matches AIApply).
- Alternative/alongside: monthly plan with an applications/day cap.
- The **fit gate** protects margin and refund rate: fewer, better applications look like quality, not volume.

## Phasing

1. **MVP:** fit gate + `apply_queue` + worker + **Greenhouse adapter only** + tailor/render PDF + evidence + auto status update. Prove the loop end-to-end on one platform.
2. **Breadth:** add **Lever + Ashby**; add **email supplement** (warmed domain, reply-to = candidate, employer-published addresses only); add `batch` mode.
3. **Scale:** more ATS, retries + monitoring, off-peak scheduling, concurrency tuning.
4. **Later/optional:** Workday, `autonomous` mode, funnel analytics (callback rate, cost per application).

## Explicitly NOT doing

- Server-side bots that log into LinkedIn/Naukri with user credentials.
- Headless mass-apply (volume without a fit gate).
- Email blasts to guessed `careers@` addresses from the main domain.
- LLM-agent-per-action browser automation (slow, token-expensive, nondeterministic) — deterministic adapters only, agent as last-resort fallback at most.

## To verify / open questions

- Confirm `undetected_chromedriver` + `selenium` (imported by `browser.py`) are installed in the runtime — **they are absent from `requirements.txt`**; either add them or migrate those scrapers to Playwright.
- Confirm each target ATS's automated-submission terms once (legal pass).
- Decide sending domain/subdomain for the email supplement + SPF/DKIM/DMARC + warm-up plan.
- Confirm VM headroom for headless Chromium alongside JobAwn's existing schedulers.
- Define `AUTO_APPLY_MIN_SCORE` threshold empirically on real score distributions.

## Verification plan

- Unit tests per adapter against **saved HTML fixtures** (no live submits in CI).
- One **manual end-to-end** submit per adapter on a real, low-stakes posting before enabling.
- Assert idempotency: a retried job never submits twice.
- Assert evidence is always captured on success.
- Load check: N queued applications respect the concurrency cap and don't disturb JobAwn's schedulers.

## Deployment

- Same Oracle VM, separate concern from the sibling product.
- Deploy via `docker cp` + `docker restart` per `docs/deployment/DEPLOYMENT_RUNBOOK.md`. **Never recreate `job-agent`.**
- Keep the apply worker off by default (`AUTO_APPLY=False`) until the first adapter is verified.

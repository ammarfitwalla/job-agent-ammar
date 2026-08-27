# Plan: refer.me-style Referral Network ("Paste a job link → Get referred")

Status: PLANNED — Phase 1 (growth version) confirmed, awaiting implementation.
Owner: Ammar
Last updated: 2026-08-27

---

## 1. Objective

Turn the existing in-app referral feature into a refer.me-style network:

> A user pastes any job URL, the system resolves the company + job title,
> lists **registered employees at that company who have opted in as referrers**,
> and lets the user send a referral request (with AI match score + resume).

**Primary goal: GROWTH.** The paste-link referral flow is the demand-side UI.
The real growth engine is **referrer supply** — seeded by Ammar's contacts and
grown by converting every job seeker into a possible referrer.

---

## 2. What already exists (reuse, do not rebuild)

| Capability | Location |
|---|---|
| Referral request lifecycle (pending → accepted/declined/cancelled → complete) | `backend/api/routes/referrals.py` |
| Dual-confirmation + `referral_credits` economy | `backend/db.py` `confirm_referral` |
| Monthly send cap (5) | `_MONTHLY_LIMIT` in `referrals.py`, `get_monthly_sent_count` |
| AI match scoring (0-100, resume-based, cached) | `_score_referral_job` / `_get_or_score_referral_job`, `POST /api/referrals/score` |
| Per-company employee discovery | `GET /api/users/at-company` → `get_users_by_company` (`db.py:1143`) |
| Referral dashboards (incoming/sent/accepted/declined) | `frontend/js/referrals.js`, `frontend/profile.html` Referral Network |
| Resume-on-profile gating for senders | `askReferral` / `sendReferralRequest` resume checks in `referrals.js` |
| Anonymized contact reveal (only on accept) | `referrals.py:182-191` |
| Existing in-app "Refer" button on job cards | `search.js` (line ~2244), `jobs.js` (line ~190) |

---

## 3. Key decisions (confirmed)

1. **URL → job details:** Best-effort parse (domain map + optional scrape),
   with manual company + title override as the safety net.
2. **Referrer discovery:** Opt-in only. Only employees who enable
   "Available for referrals" are shown in the paste-link flow, the in-app
   Refer button, and the company directory.
3. **Frontend MVP:** Modal in the app (`index.html`) "Got a job link? Get
   referred" + matching CTA on `landing.html`.
4. **Scoring:** Keep the existing AI match score in the new flow.
5. **Opt-in placement:** One-tap **"Earn referral credits" checkbox at
   registration** + visible toggle in **profile**. Buyers become sellers.
6. **Empty-state = viral loop (not a dead end).** When a pasted URL has zero
   opted-in referrers, the user gets BOTH:
   - **Invite link + credit**: shareable `/app?ref=<email>` — registering the
     friend auto-opts them in as a referrer and grants bonus `referral_credits`
     once they complete signup.
   - **Notify me**: "we'll email when a referrer at X joins."
   Shown as an empty-state card **and** a "Notify me" button near the referral
   list generally (e.g. on the company list in the modal).
7. **Supply seeding:** MVP referrer supply = Ammar's contacts at **Cognizant,
   WPP Media, TCS, Wipro, Infosys** and other large companies (pitched on
   paid-referral incentive). MAANG/FAANG recruitment deferred until the loop
   is proven.
8. **Proceed now** with the growth build (validated: don't wait to prove
   supply before building).
9. **Deployment (existing policy):** Changes stay local until Ammar says "deploy".
   Deploy method = scp → `docker cp` → `docker restart job-agent`.
   `config.py` is bind-mounted on Oracle and is never pushed to the repo.

---

## 4. Backend changes

### 4.1 URL resolver — `POST /api/referrals/resolve-url`

- File: new `backend/api/routes/joblink.py` (router prefix `/api/referrals`).
  Register in `main.py`/app router include.
- Request: `{ "url": string }` (Pydantic model).
- Response:
  ```json
  {
    "ok": true,
    "url": "https://...",
    "company": "Google",
    "company_candidates": ["Google", "Alphabet/Google"],
    "job_title": "Software Engineer",
    "source": "domain_map" | "scrape" | "manual_hint"
  }
  ```
- Pipeline (best-effort, never hard-fails):
  1. Normalize URL; require `http://` / `https://` (return 400 otherwise).
  2. **Domain map (primary, no network):** strip known patterns and map to
     `COMPANIES` from `backend/config.py`:
     - `careers.<co>.com`, `jobs.<co>.com`, `boards.<co>.com`
     - `boards.greenhouse.io/<org-slug>`
     - `jobs.lever.co/<org-slug>`
     - `linkedin.com/jobs/view/<id>` and `linkedin.com/company/<slug>`
     - `naukri.com/job/<slug>`, `naukri.com/<slug>/job`
     - `<co>.com/jobs`, `<co>.com/careers`
     - Normalize org slug → company name (strip `-jobs`, `-careers`, digits,
       lowercase fuzzy match against `COMPANIES`).
  3. **Scrape (optional enhancer, guarded):** `requests.get(url, timeout≈8)`
     with browser-ish UA; extract:
     - `og:site_name` → company hint
     - `application/ld+json` JobPosting → `hiringOrganization.name`, `title`
     - `<title>` → fallback
     - Wrap in try/except; if blocked/failed, silently continue with
       domain-map result.
  4. **Fuzzy match** resolved company against registered company names in the
     `users` table → return up to N candidates for an override dropdown.
- Rate-limit endpoint (reuse `check_rate_limit`), e.g. `resolve_url:user` 10/60s.

### 4.2 Referrer opt-in

- `backend/db.py` schema migration (guarded ALTER, style of `db.py:340-353`):
  ```sql
  ALTER TABLE users ADD COLUMN refer_opt_in INTEGER DEFAULT 0;
  ```
  Add to schema/bootstrap and test schemas that build tables from scratch
  (`tests/test_features.py`, `tests/test_integration.py`).
- `backend/db.py` helpers:
  - `update_user_refer_opt_in(email, value: int)`
  - Modify `get_users_by_company` (default) → `WHERE refer_opt_in = 1`,
    keep company-only filter. (See scope note in §8.1.)
- `GET /api/profile` → include `refer_opt_in`.
- `PUT /api/profile` and/or new `PUT /api/profile/refer-opt-in` → accept it.
- `GET /api/users/at-company` returns only opted-in users; counts reflect
  opted-in only (used by `loadCompanyUserCounts` and the referral modal).

### 4.3 Company directory — `GET /api/referrals/companies`

- Return `[{ company, referrer_count, positions: [...] }]` for companies with
  ≥1 opted-in referrer, ordered by count desc, limited (e.g. 100).
- Fuel for the landing "Browse companies" section (refer.me-style proof).
- DB: `SELECT company, COUNT(*) ... WHERE refer_opt_in = 1 AND company != '' GROUP BY LOWER(company)`.

### 4.4 Request submit — reuse existing pipeline

- `POST /api/referrals/request` unchanged (already carries `job_url`,
  `job_title`, `company`, `match_score`, `message`, `job_description`,
  `resume_text`). No backend change required here.

### 4.5 Invite + notify backend (viral loop)

- **Invite link with credit:**
  - New `POST /api/referrals/invite` → body `{ from_email, company, inviter_link }`
    OR generate a shareable URL client-side: `/app?ref=<from_email>`
    (simpler — prefer sharing a URL + storing intent on signup).
  - On user registration: if request carries `?ref=<email>`, auto-set
    `refer_opt_in = 1` for the new user and grant bonus credits to BOTH
    (referrer reward + new-user reward). Implement in `auth.py` register/
    verify path, using new helper `credit_invite_bonus(email)` in `db.py`.
- **Notify me:**
  - New table `referral_notifies` (`email`, `company`, `created_at`) OR reuse
    generic notify store; migration in `db.py`.
  - `POST /api/referrals/notify` → `{ email, company }` (idempotent upsert).
  - Background/on-demand send when the first opted-in referrer appears at a
    company (can start as a note in admin + manual email later, or SMTP at
    signup of a referrer matching a notify row — decide at impl time; keep MVP
    to storing intent + a "check your notifications" surface).
- Keep MVP lean: store notify requests; sending can be a small sweep on
  new-referrer registration (reuse `utils/smtp_sender.py`).

---

## 5. Frontend changes

### 5.1 Entry point — "Got a job link? Get referred"

- `frontend/index.html`:
  - New `referralUrlModal` (hidden, `fixed inset-0 z-50`, same pattern as
    existing `referralModal`):
    1. Step 1: URL input + "Find referrers" button.
    2. Step 2: Resolved company (editable, with candidates `<select>`) +
       job title (editable input).
    3. Step 3: Render into existing `referralUserList`-style list (opt-in
       referrers only) → reuse `askReferral` flow.
    4. Empty state (no referrers): card with **Invite link** (copyable
       `/app?ref=<email>` + company prefilled) and **Notify me** button.
  - CTA button near header/referral badge: "Got a job link? Get referred".
- `frontend/landing.html`:
  - CTA in `#referrals` section → link to `/app` and auto-open modal
    (e.g. `?refurl=1` query param handled by JS).

### 5.2 `frontend/js/referrals.js`

- New:
  - `resolveReferralUrl(url)` → calls `/api/referrals/resolve-url`.
  - `openReferralUrlModal()` / `closeReferralUrlModal()`.
  - `submitReferralUrlResolve()` → fills company/title + candidates dropdown.
  - `proceedFromUrlToReferrers()` → sets `window._referralJobUrl`,
    `window._referralJobTitle`, `window._referralCompany`, then calls
    existing `showReferralUsers(company)` (opt-in referrers list).
  - `renderEmptyState(company)` → invite link (clipboard copy) + notify button.
  - `inviteReferrer(company)`, `notifyWhenAvailable(company)` → call new APIs,
    showToast on success.
- Reuse (no change): `askReferral`, `sendReferralRequest`, resume gating,
  score display, withdraw, dashboards.
- Registration flow (`js/auth.js`): parse `?ref=<email>`; auto-check
  "Available for referrals" → `refer_opt_in` at signup.

### 5.3 Profile + registration opt-in control

- `frontend/profile.html` edit modal: "Checkbox: Available for referrals".
- `frontend/js/profile.js`: save via `PUT /api/profile` (include `refer_opt_in`);
  badge on own profile + in referral lists ("✓ Available for referrals").
- `frontend/index.html` registration modal (in `auth.js`): one-tap
  "Earn referral credits by referring others" checkbox (default on for
  invited users, off otherwise).

---

## 6. Landing page copy (refer.me-style social proof)

- Update `#referrals` section: "Paste any job link, get referred by an insider
  at the company" + 3-step explainer + CTA.
- Optionally render company directory (`GET /api/referrals/companies`) as a
  chip grid with referrer counts.
- Add a "Refer talent and earn" supply-side pitch (position turnaround).

---

## 7. Testing / verification

- Existing suites must still pass:
  - `backend/tests/test_features.py`
  - `backend/tests/test_integration.py`
  (pytest; confirm command before running.)
- Add tests:
  - resolve-url: valid LinkedIn/greenhouse/lever/naukri/careers URLs →
    company + title; garbage URL → 400; blocked scrape → domain-map fallback.
  - opt-in: at-company filters to `refer_opt_in = 1`; profile PUT persists it.
  - companies endpoint: only counted companies have opt-in referrers.
  - invite: new user via `?ref=` auto-opts-in + credits granted to both.
  - notify: idempotent upsert; notifies fired on new referrer at a company.
- Static checks after edits: `python -m py_compile` on backend files,
  `node --check` on JS files.

## 8. Open questions / scope notes

1. **Opt-in behavior change for existing in-app Refer button:**
   Filtering `at-company` to opted-in means currently-registered employees who
   never toggled the flag disappear from ALL referral discovery until they opt
   in. Confirmed: **yes, opt-in only everywhere.** Mitigation: prominent opt-in
   at registration + profile + one-time banner prompt on existing users.
2. Scrape reliability varies by site (anti-bot). Domain map + manual override
   is the safety net so UX never hard-fails.
3. Self-refer (user pasting a URL for their own opted-in company/profile) →
   already rejected by "You can't refer yourself" in the request flow.
4. `referral_credits` are currently counted/shown but not yet redeemable —
   making them spendable (redemption, referral-bonus display, leaderboard) is a
   Phase 2 supply-incentive item.
5. Notify sending mechanics: MVP = store intent (+ optional SMTP sweep on new
   referrer). Full in-app notification center is later.

---

## 9. Pending work NOT part of this plan (tracked elsewhere)

- NVIDIA provider integration (Nemotron-3-Super-120B-a12b as primary LLM,
  Groq fallback) — config `NVIDIA_API_KEY`/`NVIDIA_MODEL`, new
  `NvidiaProvider`, `llm_client.py` wiring.
- Stats bar removal from `/app` (index.html + search.js) + profile resume
  delete-on-re-upload (profile.py) — edits complete locally, not yet deployed.
- No deployments happen until Ammar explicitly says "deploy"
  (copy-paste workflow: scp → docker cp → docker restart).
  `config.py` never committed/pushed (contains live secrets).

## 10. Supply seeding checklist

- [ ] Recruit Ammar's contacts at **Cognizant, WPP Media, TCS, Wipro, Infosys**
      to register + opt in as referrers (paid-referral pitch).
- [ ] For each: verify position/company (manual at first), enable opt-in.
- [ ] Confirm at least 2-3 opted-in referrers at ~5 companies before marketing
      the paste-link feature.
- [ ] After loop is proven: begin MAANG/FAANG referrer recruitment.
- [ ] Aim: every new user is offered the opt-in (buyers → sellers).

## 11. Implementation order (suggested)

1. `db.py`: migration (`refer_opt_in`, `referral_notifies`) +
   `update_user_refer_opt_in` + `get_users_by_company` opt-in filter +
   company-directory + invite-credit + notify helpers.
2. `joblink.py`: resolve-url route + tests.
3. `referrals.py`/`users.py`/`profile.py`/`auth.py`: expose opt-in, companies,
   invite, notify endpoints.
4. `referrals.js` + `index.html`: URL modal flow + empty-state (invite/notify).
5. `profile.html`/`profile.js` + `auth.js`: opt-in toggle at profile + registration.
6. `landing.html`: CTA + copy (+ company chips if decided).
7. Run tests + static checks → report to Ammar → wait for deploy go-ahead.
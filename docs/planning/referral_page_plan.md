# Plan: Dedicated public `/referrals` page

## Goal
A dedicated public page where visitors can:
1. Browse companies that have enrolled (opt-in) employees/referrers.
2. Select a company.
3. Paste the job link.
4. Ask an insider for a referral.

**Out of scope:** No AI scoring on this page (decision: skip scoring). No deploy/push until explicitly requested.

## Decisions (from user Q&A)
- Employee positions + counts are shown **publicly**; only the **Ask** action requires login.
- **Skip AI match scoring** on this page (`skip_score` flag on the request endpoint).
- Resume remains **required** to send a request (auto from profile, or inline upload).
- Link placement: only point the landing "Get Referred" CTA (`/app?refurl=1`) at `/referrals`. No nav/footer changes.

## Existing building blocks (all live in prod, reuse)
- `GET /api/users/referrer-directory` (public) — companies + referrer counts, opt-in referrers only
- `GET /api/users/at-company?company=X` (public) — anonymized referrers: opaque id + position, no name/PII
- `GET /api/users/company-counts` (public)
- `POST /api/referrals/resolve-url` (public) — pasted link → company + guessed job title
- `POST /api/referrals/request`, `GET /api/referrals/outgoing`, `/api/referrals/remaining`, `POST /api/profile/resume` — login-gated
- Login: reusable `#authModal` + `auth.js` OTP flow
- Ask UI logic copied from `frontend/js/referrals.js` (message box + resume row + send + per-referrer state buttons)

## Change list

### Frontend — new files
1. `frontend/referrals.html`
   - Public page, same Tailwind / Plus Jakarta Sans look as `landing.html`.
   - Hero + 3-step layout (Browse companies → Paste job link → Ask an insider).
   - Embeds the reusable `#authModal` for login.
   - Includes `js/api.js`, `js/auth.js`, `js/terms.js`.

2. `frontend/js/referrals-page.js` (self-contained; do NOT import `referrals.js`, it is coupled to search-page DOM)
   - Directory grid: `GET /api/users/referrer-directory` → company cards with referrer counts. Empty → friendly state.
   - Paste link: `POST /api/referrals/resolve-url` → auto company + job title. If company differs from the selected one, warn "link points to X, not Y".
   - Referrer list: `GET /api/users/at-company` → positions public; Ask behind login.
   - Ask: inline message box + resume row (profile resume auto, else upload via `POST /api/profile/resume`). Monthly counter from `/api/referrals/remaining`. Per-referrer state from `/api/referrals/outgoing` (Ask / Withdraw / Pending / Accepted / Declined).
   - Send: `POST /api/referrals/request` with `skip_score: true`.

### Backend — 2 small edits
3. `backend/api/main.py`
   - Add `/referrals` → `FileResponse(frontend/referrals.html)` (mirror the `/app` / `/profile` handlers).
   - Add `/referrals` to the auth-guard public path list.

4. `backend/api/routes/referrals.py`
   - Add `skip_score: bool = False` to `ReferralRequest`.
   - In `referral_create` (`referrals.py:153-156`): if `req.skip_score` is true, skip `_get_or_score_referral_job` and store `req.match_score` as-is.
   - Existing app flow unaffected (never sends the flag).

### Landing CTA
5. `frontend/landing.html`
   - Hero secondary CTA `href="/app?refurl=1"` → `href="/referrals"` (and same link in the referrals section if it points there).

## Tests & verification
- `TestReferralPage` (mirror `TestAdminBackup` style in `backend/tests/test_integration.py`):
  - `GET /referrals` serves HTML.
  - `skip_score=true` request does NOT invoke `_get_or_score_referral_job` (mocked) and stores score 0.
  - Request still created; monthly limit still enforced.
- Run full suite (currently 90 tests), `py_compile`, `node --check`.
- Manual walkthrough in dev: directory loads, resolve detects company, ask sends without scoring.

## Deploy
- Only commit/push/deploy when the user explicitly asks.

## Relevant files
- `backend/api/routes/users.py` — `referrer-directory:38`, `at-company:16`, `company-counts:28`
- `backend/api/routes/referrals.py` — `ReferralRequest:94`, `referral_create:127`
- `backend/api/main.py` — page redirects `:268-293`; auth-guard public lists
- `frontend/js/referrals.js` — reference UI logic: resolve-url flow `:130`, ask `:517`, send `:553`, resume row `:471`, state buttons `:354`
- `frontend/landing.html` — hero CTA `:132`, referrals-section CTA `:308`
- `frontend/index.html` / `frontend/js/auth.js` — `authModal` markup + OTP flow to copy/reuse
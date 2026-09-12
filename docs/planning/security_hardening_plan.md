# Plan: Security hardening

## Goal
Low-cost, high-value security hardening of the shipped app (jobawn.com). Adopted subset from the proposed list (2.1–2.4, 3.2, 3.3); **CSRF tokens skipped** — auth is a `Bearer` JWT in `localStorage["ja_token"]` sent via `Authorization` header (`frontend/js/api.js:6-37`), no cookies, so there is no ambient-credential CSRF vector. CORS tightening covers the meaningful cross-origin surface.

## Recommended order
1. Tighten CORS
2. Security headers (2.2)
3. CSP meta tags (2.1)
4. Pin CDNs + SRI (2.3)
5. Server-side input length validation (3.2)
6. Referral-value escaping (2.4) — folded into referral page work
7. Resume text storage (3.3) — already PENDING_TASKS #6

---

## 1. Tighten CORS
`backend/api/main.py:65-71` currently:
```python
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
```
- Restrict `allow_origins` to `https://jobawn.com` and local dev origin(s) (`http://localhost:7860`).
- Keep `allow_credentials=True` only with explicit origins (never wildcard); response is JSON over `fetch` with explicit `Authorization` headers.
- Verify the app has no other legitimate cross-origin consumers (admin page is same-origin at `/admin`).

## 2. Security headers (2.2)
Extend the existing `no_cache_frontend` middleware (`backend/api/main.py:76-87`) or add a sibling middleware setting, on **all** responses:
- `X-Frame-Options: DENY`
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: strict-origin-when-cross-origin`

## 3. CSP meta tags (2.1)
Pragmatic policy — the app relies on inline `onclick=` handlers everywhere and Tailwind Play CDN injects `<style>`, so `'unsafe-inline'` stays for now. Add `<meta http-equiv="Content-Security-Policy">` to the `<head>` of **all four pages** (landing, index, profile, admin) and the future `/referrals` page:
```
default-src 'self';
script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://cdn.jsdelivr.net;
style-src 'self' 'unsafe-inline' https://fonts.googleapis.com;
font-src 'self' https://fonts.gstatic.com;
img-src 'self' data:;
connect-src 'self' https://api.countrystatecity.in https://api.emailjs.com;
frame-src 'none';
```
- Blocks arbitrary script origins; still blocks iframe embedding (reinforces `X-Frame-Options: DENY`).
- Tailwind Play CDN has no SRI — revisit removal later; bundling styles would let us drop `'unsafe-inline'`.

## 4. Pin CDNs + SRI (2.3)
- **`@emailjs/browser@4`** (`index.html:42`, `profile.html:8`) — floating minor; pin to the exact current `4.x.y` and add `integrity="sha384-..." crossorigin="anonymous"` (jsdelivr provides SRI).
- **`chart.js@4.4.7`** (`admin.html:11`) — already pinned; add `integrity` + `crossorigin="anonymous"`.
- **Tailwind** (`cdn.tailwindcss.com` in all 4 pages) — pin the version path (`https://cdn.tailwindcss.com/3.4.x`); **no SRI available** for the Play CDN. Document the limitation.
- Google Fonts (`fonts.googleapis.com` / `fonts.gstatic.com`) — no integrity; already fine.
- Compute SRI hashes at implementation time via `https://cdn.jsdelivr.net/gh/...` `integrity` attribute (use `openssl dgst -sha384 -binary | openssl base64 -A` on the fetched file).

## 5. Server-side input length validation (3.2)
Add `max_length` / bounds to the Pydantic models for **stored user input** (client `maxlength` already exists on several inputs; server is what matters):
- `backend/api/routes/profile.py` — `UpdateProfileRequest` (name 50, company 100, position 100, linkedin_url 2083), `UpdateNameRequest` (50).
- `backend/api/routes/referrals.py` — `ReferralRequest` (job_url 1000, job_title 200, company 200, message 500, resume_filename 200), `NotifyRequest`/`InviteRequest` (company 200), `ReferralScoreRequest` (job_description/resume_text bounded by a generous cap, e.g. 50_000).
- `backend/api/routes/auth.py` — `RegisterRequest`/`AddCompanyRequest` name/company caps if any stored.
- Creates a 422 on violation; existing clients already cap at these sizes, so no UX change.

## 6. Referral-value escaping (2.4) — folded into referral work
Values are server JSON already `htmlEscape`d at render; the risky pattern is inline `onclick="inviteReferrer('<..>')"` / `notifyWhenAvailable('<..>')` arg building (`frontend/js/referrals.js:330-337`). Add a shared `escapeAttr()` (HTML-escape + single-quote-safe + length cap) and use it for `_referralCompany` and candidate values. Apply while building the new referrals page and touching `referrals.js`.

## 7. Resume text storage (3.3) — already PENDING_TASKS #6
Plaintext `jobagent_resume_text` in localStorage (`frontend/js/search.js:34`), read by `frontend/js/referrals.js:388`. Do as part of PENDING #6: first step move to `sessionStorage`; optional Web Crypto AES-GCM later.

---

## Verification
- `py_compile` backend; `node --check` touched JS.
- Full test suite (90 → ~93 after location work; confirm security changes don't break it).
- Manual: each page loads with CSP intact (console shows no blocked-request errors); external API calls (`/states`, EmailJS, countrystatecity) still work; admin resume downloads still work; registrations/profile flows unchanged.
- Cross-origin check: `curl -H "Origin: https://evil.example" ...` → no `Access-Control-Allow-Origin` for evil origin; security headers present on all responses.

## Deploy
- Only commit/push/deploy when the user explicitly asks.

## Relevant files
- `backend/api/main.py` — `CORSMiddleware:65-71`, `no_cache_frontend:76-87`
- `frontend/landing.html` (CDN: 9-13), `frontend/index.html` (7-10, 42), `frontend/profile.html` (7-9), `frontend/admin.html` (8-11)
- `frontend/js/api.js:6-37` — Bearer token handling (why CSRF is skipped)
- `frontend/js/referrals.js:330-337` — inline onclick arg pattern
- `frontend/js/search.js:34` — `RESUME_CACHE_KEY`
- `backend/api/routes/profile.py`, `referrals.py`, `auth.py` — Pydantic models for validation
- `docs/planning/PENDING_TASKS.md` — #6 (resume storage), #8 (referral page) where items 6–7 fold in
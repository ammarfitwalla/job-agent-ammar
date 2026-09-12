# Pending Tasks

Task numbering follows the discussion on 2026-09-07. Items 3 and 6 pending; carry-over items at the end. Done and removed: #4 JWT auth, #5 API auth, #7 NVIDIA provider (all deployed 2026-09-11).

## 3. Add city to location search (currently state + country only)

**What/why:** The search location autocomplete only returns country and state matches. Users should be able to pick a city (e.g. "Austin, TX, US", "Bengaluru, India").

**Current wiring (already partially there):**
- `frontend/js/search.js:1342-1445` — location autocomplete. Loads `/states`, builds **only country + state matches** (`search.js:1387-1411`), label = `[state, country].join(", ")` (`:1407`), select sets `state/country/country_code` (`:1423-1445`).
- Search payload already carries `city` (`search.js:1602` `city: (loc && loc.city) || ""`), but the autocomplete never populates `loc.city`.
- `backend/api/routes/states.py` — `/states` returns a flat `list[{state, country, country_code}]`, no cities (`states.py:38-43`). Uses `countrystatecity_countries` (`states.py:3`).
- Job cache is already keyed per-city (`db.py:194,211…` UNIQUE includes `city`), and `get_cached_jobs` has specificity fallback exact(city,state,country) → (state,country) → (country) (`db.py:597-598`). Prewarm expands Naukri into per-city entries (`scrape.py:182-195`, `scheduler.py:64-77`; `config.CACHE_STATE_CITIES`).

**Scope:**
1. Extend `/states` (or add `/states?q=`) to also return city matches with labels, using the countrystatecity lib (add `get_cities_of_state` — confirm the package exports it; add to requirements if in another package).
2. Frontend: add city tier to the match builder (`search.js:1387-1411`), include `city` in the selected location object + label format "City, State, Country" (`:1407`, `:1497`).
3. Keep `getLocation` `_locLabel` state+country fallback when city empty (`:1491-1497`).
4. Update placeholder `index.html:261` to hint cities.
5. Cache miss on a city → existing fallback serves state-level jobs; verify UX shows them with city label.

**Acceptance:** typing a city returns it; selecting it runs the search with `city` populated in the request; results still load when the city has no cache entry.

**Current state:** `frontend/js/search.js:34` `RESUME_CACHE_KEY = "jobagent_resume_text"`; read at `frontend/js/referrals.js:388` for pre-fill. Resume is also sent to the server over HTTPS for scoring/keywords — the concern here is the browser-resident plaintext copy.

**Scope (ranked):**
1. Encrypt at rest: Web Crypto AES-GCM, key held in `sessionStorage` (fresh per tab session); decrypt when the referrals flow needs it; erase key + ciphertext on logout.
2. Or drop to `sessionStorage` plaintext (cleared on tab close; simplest).
3. Either way, keep the resume textarea fallback so referral pre-fill fails soft.

**Acceptance:** no plaintext resume PII in `localStorage`; referrals re-runs still pre-fill within the same session; OTP/referral flows unaffected.

---

## Carry-over (decided earlier, not in the numbered list)

- **Load test:** `docs/planning/loadtest-plan-2026-09-07.md` written and approach agreed (k6 vs prod, unique X-Forwarded-For per VU) — not run yet; **k6 not installed locally**; needs a go/no-go before hammering prod.
- **Housekeeping:** `backend/config.py` intentionally uncommitted (secrets; server copy is source of truth). `stop_on_old.md` + `tmp_usage.json` are untracked scratch — keep or delete.

---

## 8. Dedicated public `/referrals` page

**What/why:** Visitors browse companies with enrolled (opt-in) referrers, select a company, paste a job link, and ask an insider for a referral.

**Decisions (2026-09-12):** positions/counts shown publicly (only "Ask" requires login); AI match scoring skipped (`skip_score` flag); resume required to ask; landing "Get Referred" CTA (`/app?refurl=1`) pointed at `/referrals`.

**Plan:** `docs/planning/referral_page_plan.md` (frontend page + page JS, `/referrals` route + public path in `backend/api/main.py`, `skip_score` in `backend/api/routes/referrals.py`, landing CTA change, `TestReferralPage`) — full change list there.

**Not started.** Deploy only when the user explicitly asks.

---

## 10. Security hardening

**What/why:** Cheap high-value hardening. Adopted subset from proposed list (2.1-2.4, 3.2, 3.3); **CSRF tokens skipped** (auth is Bearer JWT in localStorage, no cookies — no ambient-credential vector).

**Plan:** `docs/planning/security_hardening_plan.md`. Items in order: tighten CORS (`main.py:65-71` `allow_origins=["*"]`), security headers middleware (2.2), pragmatic CSP meta on all pages (2.1), pin/SRI CDNs (2.3; Tailwind Play CDN has no SRI), server-side `max_length` on stored Pydantic fields (3.2).

**Folded into existing tasks:** referral-value escaping (2.4) → #8 referral page; resume text storage (3.3) → #6.

**Not started.** Deploy only when the user explicitly asks.

---

## 9. User location (state/country) + admin registrations columns

**What/why:** Collect user location (state + country) on the profile edit page, and show Location + Resume link columns in the admin **sessions → registrations** tab.

**Decisions (2026-09-12):** reuse the search-page location autocomplete text box on the profile page (no free-text inputs); state/country optional on save; only state/country stored (city ignored).

**Plan:** `docs/planning/user_location_plan.md` (shared `location-picker.js` extracted from `search.js`, users table migration + `update_user_profile`, profile API pass-through, new `/api/admin/users/{email}/resume` endpoint, profile page edit/display, admin registrations columns, `TestUserLocation`).

**Not started.** Deploy only when the user explicitly asks.

---

## 11. Careers tab — jobs from company career pages

**What/why:** Pull open roles directly from company career pages (ATS APIs + sitemaps + JSON-LD, adopting [jobseek](https://github.com/colophon-group/jobseek) monitor patterns — MIT, no CC BY-NC data reuse) and surface them on a dedicated Careers page/tab.

**Decisions (2026-09-12):** admin-managed company list with auto-detect; ATS APIs + sitemap + JSON-LD monitors; separate Careers page (not merged into board cache); daily scheduled pull + manual admin refresh.

**Plan:** `docs/planning/careers_page_plan.md` (`career_sources`/`career_jobs` tables, `careers_scraper.py` monitor registry incl. Greenhouse/Lever/Ashby/SmartRecruiters/Workable, `careers.py` public+admin routes, `/careers` page + link, scheduler job, admin Careers tab, `TestCareers`).

**Not started.** Deploy only when the user explicitly asks.
# Pending Tasks

Task numbering follows the discussion on 2026-09-07. Items 3–6 pending per explicit request; carry-over items at the end.

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

## 4. Add JWT auth

**What/why:** No token-based identity exists today. Auth is OTP+email only; after verification the client is "whoever claims an email".

**Current state:** `backend/api/routes/auth.py` OTP flow (verification_codes table; SMTP/EmailJS send). Search identity is a separate `sessions` table. Profile/resume/admin endpoints trust a client-supplied `email` string (see task 5).

**Scope:**
1. Add `JWT_SECRET` (or derive from existing secret in `backend/config.py` — server copy only, never commit) + expiry config.
2. New `backend/utils/jwt.py`: `create_token(email, role)`, `decode_token`, FastAPI `Depends(get_current_user)` dependency (409-401 on bad/expired).
3. Issue on successful OTP verify in `auth.py`; expose via `Authorization: Bearer`.
4. Decide token storage on the client (see task 6 for the same storage question; key-materials vs token in localStorage/sessionStorage).

**Acceptance:** verify-by-email returns a signed token; `/api/auth/me` style call returns the claimed email from the token, not from a request field.

## 5. Auth for APIs (replace client-supplied identity)

**What/why:** Multiple endpoints treat a caller-supplied `email` as proof of identity (IDOR / admin impersonation).

**Affected, verified:** `backend/api/routes/admin.py` — no dependency guards; mutators check `email != ADMIN_EMAIL` against the **client-supplied** field (`admin.py:345, 399, 415, 444, 500`); read-only admin endpoints (`/api/admin/stats, /sessions, /scores, /db/info, /visits, /leads, /server, /cache-stats`) are fully public. `backend/api/routes/profile.py` — GET/PUT `/api/profile`, `/api/profile/resume*`, `/refer-opt-in` keyed by `email` query param (anyone can read/overwrite another user's profile or resume text).

**Scope:**
1. Apply `get_current_user` (task 4) to profile + resume + saved_jobs + referrals routes; replace `email` params with `Depends(get_current_user)`.
2. Admin: mutating routes require a token whose decoded email == `ADMIN_EMAIL` (server-side check), not a request field; read-only admin routes behind an admin-auth (or at least the same JWT + ADMIN_EMAIL).
3. Keep the frontend working: admin.js + profile/referrals/localStorage flows must send the bearer token (or add an admin OTP flow for the admin page).

**Acceptance:** `/api/profile?email=<other>` and `/api/admin/*` return 401/403 without a valid token and 403 when the token's email isn't the target/admin. Confirmed smoke-test repro before change: `GET https://jobawn.com/api/admin/stats` → 200 unauthenticated.

## 6. Resume text storage (localStorage → encrypted or session)

**What/why:** Resume PII persists in plaintext in `localStorage["jobagent_resume_text"]` with no expiry.

**Current state:** `frontend/js/search.js:34` `RESUME_CACHE_KEY = "jobagent_resume_text"`; read at `frontend/js/referrals.js:388` for pre-fill. Resume is also sent to the server over HTTPS for scoring/keywords — the concern here is the browser-resident plaintext copy.

**Scope (ranked):**
1. Encrypt at rest: Web Crypto AES-GCM, key held in `sessionStorage` (fresh per tab session); decrypt when the referrals flow needs it; erase key + ciphertext on logout.
2. Or drop to `sessionStorage` plaintext (cleared on tab close; simplest).
3. Either way, keep the resume textarea fallback so referral pre-fill fails soft.

**Acceptance:** no plaintext resume PII in `localStorage`; referrals re-runs still pre-fill within the same session; OTP/referral flows unaffected.

---

## Carry-over (decided earlier, not in the numbered list)

- **Load test:** `loadtest-plan-2026-09-07.md` written and approach agreed (k6 vs prod, unique X-Forwarded-For per VU) — not run yet; **k6 not installed locally**; needs a go/no-go before hammering prod.
- **Housekeeping:** `backend/config.py` intentionally uncommitted (secrets; server copy is source of truth). `stop_on_old.md` + `tmp_usage.json` are untracked scratch — keep or delete.

---

## 7. NVIDIA provider (Groq → fallback)

**What/why:** Make NVIDIA NIM the primary LLM provider, with Groq catching failures. Spec supplied 2026-09-07; changes drafted then reverted to this file only.

**Spec:**
1. `backend/config.py` — add:
   - `NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY", "")`
   - `NVIDIA_MODEL = os.environ.get("NVIDIA_MODEL", "nvidia/nemotron-3-super-120b-a12b")`
   - `NVIDIA_KEYWORDS_MODEL` → same model constant (single model for both roles)
2. `backend/llm/providers.py` — add `NvidiaProvider(BaseProvider)` using the already-installed openai SDK:
   - `OpenAI(base_url="https://integrate.api.nvidia.com/v1", api_key=key)`
   - `client.chat.completions.create(model=m, messages=[{"role":"user","content":prompt}], temperature=0.1, max_tokens=max_tokens, top_p=0.95, stream=False, timeout=30)`
   - Same TokenBucket throttle + 3-attempt backoff loop as `GroqProvider`.
3. `backend/llm/llm_client.py` — register `"nvidia"` (scoring) + `"nvidia_keywords"` providers; set `_FALLBACK_CHAIN = ["groq"]` so NVIDIA is primary and Groq catches failures. Callers (`chat`/`batch_chat`/`keyword_chat`) unchanged.

**Implementation notes (checked 2026-09-07):**
- `openai` SDK 2.44.0 and `groq` 1.5.0 both installed; already in `backend/requirements.txt:27-28`.
- `_route()` picks primary via `_providers.get(LLM_PROVIDER)` and its fallback loop skips `name == LLM_PROVIDER` (`llm_client.py:52-60`) — so **`LLM_PROVIDER` default must flip to `"nvidia"`** (currently `"groq"`) for NVIDIA to actually be primary.
- `keyword_chat()` currently hardcodes `_providers.get("groq_keywords")` with no fallback (`llm_client.py:33-36`) — needs a parallel `LLM_PROVIDER + "_keywords"` primary with `"groq_keywords"` fallback.
- An empty-`NVIDIA_API_KEY` guard in `NvidiaProvider` makes unconfigured runs fall fast to Groq (otherwise each call would 401 after a network round-trip).

**Deployment notes:**
- Do **not** deploy local `backend/config.py` (secrets). The container's own `/app/backend/config.py` must be updated (append the 3 NVIDIA constants) **before** shipping `llm_client.py`, or the app import-crashes.
- NVIDIA_API_KEY for prod goes via container env (`docker run -e NVIDIA_API_KEY=...`) or the container's config — needs the key from the user; until then everything falls back to Groq (safe).
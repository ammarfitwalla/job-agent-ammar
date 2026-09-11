# JWT Auth Plan

Replace the current "everything public, identity trusted from client-supplied `email`" model with a
default-deny API protected by signed JSON Web Tokens. Successful OTP login mints a JWT; the browser
sends it as `Authorization: Bearer <token>` on every protected call. Whitelisted public endpoints
stay open by design; everything else is gated (401 without a token, 403 for admin-class routes).

Decisions confirmed by the user:

| Decision | Choice |
|---|---|
| Gate model | Default-deny + explicit public whitelist |
| Search funnel | Kept public (anonymous-first flow preserved) |
| Token storage | `sessionStorage` (cleared on tab/browser close) |
| Register flow | OTP must be verified first (register requires a token) |
| Token TTL | 24h access token (no refresh; session cleans up on close) |
| Admin identity | Token email == `ADMIN_EMAIL` (`ammarfitwalla@gmail.com`, case-insensitive) |
| /docs | Admin-only, same class as `/api/admin/*` |

---

## Part 1 — What stays public and why

The whitelist below requires **no token**. Static assets and page routes must stay open or the site
itself cannot load. The remaining API entries cluster into four justifications:

1. **Trivial data** — no personal data, no write side effects of consequence.
2. **The login mechanism itself** — gating these makes it impossible to ever obtain a token.
3. **The anonymous search funnel** — the core product flow is *look, paste resume, search before
   logging in*. Gating these would put a login wall in front of the main value.
4. **Privacy-scrubbed directory / telemetry** — outputs are already anonymized (opaque id + position,
   counts only) or are anonymous pre-login beacons.

### Pages + static

| Path | Why public |
|---|---|
| `/`, `/app`, `/profile`, `/admin` | The HTML pages themselves; the *data APIs they call* are gated. `/admin` page is public shell, its admin API is not. |
| `/js/*`, `/css/*`, all `.html`, images/favicon | The frontend cannot render without them. |

### Funnel + landing + auth

| Endpoint | Why public |
|---|---|
| `/health` | Uptime probe, no data. |
| `/api/stats/public` | Landing counters (jobs, companies). |
| `/api/auth/send-code`, `/api/auth/verify-code` | The login mechanism. Gating these is self-defeating. |
| `/api/auth/companies` GET | Role/company dropdown, static list. |
| `/api/users/referrer-directory` | Opt-in companies only. |
| `/api/users/at-company` | Already privacy-scrubbed: returns only opaque id + position, no email/name/linkedin (`users.py`). Rate-limited per IP. |
| `/api/users/company-counts` | Counts only; `user_email` was used solely to exclude self from the count. **Optional auth** (`get_optional_user`): token present → excludes self, anonymous → plain counts. `user_email` param removed server-side (see Part 3.5, Part 5). |
| `/api/visit/start`, `/api/visit/ping`, `/api/visit/end` | Pre-login telemetry beacons. |
| `/api/events` | Anonymous usage telemetry. |
| `/api/referrals/resolve-url` | Referral link lookup; inbound referral clicks happen pre-login. Stays public (see Part 5). |
| `/api/leads` POST | Public subscribe form. GET stays admin-only. |
| `/jobs` GET, `/jobs/{index}`, `/jobs/check-relevance` | The anonymous search flow. Bound by `search_id` + existing IP rate limits. Job data is public job-board data. |
| `/scrape`, `/scrape/stop`, `/scrape/status` | Search drive loop for the current session. Session-bound. |
| `/resume/upload`, `/resume/keywords` | Paste-resume-before-login flow. The pasted text is user-supplied and keyword extraction happens at upload time. |
| `/states` | Static country/state autocomplete list. |
| `/roles` GET | Static role suggestion list. |
| `/votes` GET, `/votes` POST | Public rally counter. DELETE is admin-only. |

---

## Part 2 — What stays gated and why

Everything **not** in Part 1 is default-deny. These are the "client tells us who you are" endpoints
we are fixing. Today they accept `email` / `from_email` in the body or query and trust it — anyone who
guesses another user's address can read their profile, resume, saved jobs, referral requests, or do
admin actions. After this change the server derives identity from the **token**, never from the
request.

### User-scoped (token required, 401 without — identity from token, no client email)

| Endpoint | Why gated |
|---|---|
| `/api/profile/*` (`GET`, `PUT`, `PUT /name`, `PUT /refer-opt-in`, `POST /resume`, `GET /resume`, `GET /resume/text`) | Profile + resume text are personal data. Today `GET /api/profile/resume/text?email=X` returns anyone's resume. |
| `/api/saved-jobs/*` (`POST`, `GET`, `GET /check`, `POST /batch-check`, `PATCH /{id}/status`, `DELETE /{id}`) | Private job application tracking; currently keyed by arbitrary email. |
| `/api/referrals/*` except `resolve-url` (`request`, `incoming`, `outgoing`, `accept`, `decline`, `complete`, `confirm`, `withdraw`, `remaining`, `invite`, `notify`, `notifies`, `score`, `resume`) | Referral requests expose contact + resume data. `from_email` in request bodies will be replaced by the token email. |
| `POST /api/auth/register` | Today anyone can create/claim any account by email **without owning it**. Now requires a token issued by OTP verification. |
| `POST /api/auth/companies` | Writes a company to shared data; keep it to known users. |
| `/roles/custom` POST, DELETE | Persists per-user custom roles; user-scoped write. |
| `/resume/download`, `/resume/storage` DELETE | Downloads the stored resume file for an email / deletes it. Personal file access + destruction. |

### Admin-only (token required AND token email == `ADMIN_EMAIL`, else 403)

| Endpoint | Why gated |
|---|---|
| `/api/admin/*` (all 20: stats, sessions, scores, registrations, users CRU, visits, leads, db/info, db/restore, db/merge, resume/upload, prewarm, cache-stats, server) | Full user/data visibility and destructive ops (DB restore/merge). Currently fully public — reads worked unauthenticated (smoke-tested). |
| `/api/leads` GET | Subscriber lead data (emails). |
| `/db` | **Full database download** — currently public. |
| `/logs` | Full visit log with IP addresses. |
| `DELETE /votes` | Resets the public counter. |
| `/docs`, `/redoc`, `/openapi.json` | Full API schema exposed to attackers — unnecessary discovery surface. Swagger UI still usable for the admin (Authorize → paste Bearer token). |

---

## Part 3 — Implementation plan

### A. Auth foundation (backend)

1. `backend/utils/jwt.py` — HS256 JWT.
   - `create_token(email, expires_minutes=1440)` → signed `header.payload.signature`.
   - `decode_token(token)` → payload dict or raise.
   - Secret from `config.JWT_SECRET = os.environ.get("JWT_SECRET", "")`. **No per-process fallback is
     allowed** — a random per-process secret would intermittently 401 in any multi-worker deployment
     (worker A signs, worker B can't verify). The secret must be set in the environment (or the
     server-side `config.py`). Add the constant to `config.py` + `config.example.py`. **`config.py`
     is never committed** (real secrets); the deployed container has its own copy.
   - **Startup fail-fast** (in `main.py` lifespan): if `JWT_SECRET` is empty and not `DEV_MODE` →
     `raise RuntimeError("JWT_SECRET is not set")`. Missing secret fails loudly on boot, never as an
     intermittent runtime error.
   - **DEV_MODE** uses a fixed literal dev secret (not random) so multi-worker dev and the test suite
     agree on a single key. The literal is never shipped to production.
2. `backend/api/deps.py` — `get_current_user` and `get_optional_user` share **one strict Bearer
   parser**:
   - Scheme must equal `Bearer` (case-insensitive) and the token must be non-empty.
   - Header missing, wrong scheme, garbage, malformed, expired, or signature-failed → clean
     `401 {"detail":"Invalid or missing credentials"}` — **never 500**.
   - Success returns `{"email": ...}`; `get_optional_user` returns `None` when absent.
3. `backend/api/routes/auth.py`
   - `POST /verify-code` returns a `token` on success — both the normal path and the DEV_MODE
     **123456** path.
   - `POST /register` gains `Depends(get_current_user)` → unverified registration is impossible.
4. `backend/api/main.py` — security middleware (registered with the app) that:
   - **Short-circuits before any auth logic**: `if request.method == "OPTIONS"` → pass through
     unconditionally (CORS preflight must never 401; harmless even though frontend/backend are
     same-origin today).
   - Parses the Bearer token with the same strict parser as `deps.py` into `request.state.user`
     (or marks absent).
   - Applies rules by path:
     - Public whitelist (Part 1) → pass through.
     - User-scoped → 401 without a valid token.
     - Admin-class (`/api/admin/*`, `/api/leads` GET, `/db`, `/logs`, `DELETE /votes`, `/docs`,
       `/redoc`, `/openapi.json`) → 401 without token, 403 if email != `ADMIN_EMAIL`.
   - **Admin email compare at compare time**: `state.email.lower() == ADMIN_EMAIL.lower()` (both
     sides lowercased; never rely on documented intent).
   - `/docs`, `/redoc`, `/openapi.json` are FastAPI-native routes matched by **exact path**; the
     middleware wraps the whole ASGI app pre-routing, so gating them actually engages. FastAPI-native
     routes take precedence over the static mount at `/`, so no static-file interference.
   - Coexists with the existing `no_cache_frontend` middleware (public).
5. Identity swap — replace client-supplied `email` (body/query) with `request.state.user.email` in:
   - `profile.py` (all handlers)
   - `saved_jobs.py` (create/list/check/batch-check/patch/delete)
   - `referrals.py` (all except `resolve-url`)
   - `resume.py` (`download`, `storage` delete)
   - `jobs.py` `check-relevance` (rate-limit key: token email if present, else IP)
   - `admin.py` mutators (email comes from token; compare against `ADMIN_EMAIL`)
   - `users.py` `company-counts` — **optional auth** (`get_optional_user`): with a token, exclude the
     token email from counts; anonymous → plain counts (no `user_email` query param anymore). Funnel
     display survives and the opt-in enumeration leak closes.
6. **Proxy/IP note (already handled, confirmed)**: `utils/client_ip.py` already prefers the first
   `X-Forwarded-For` entry (set by nginx) with a socket-peer fallback, so IP-keyed rate limits work
   behind the proxy. Deploy audit item: confirm nginx is the **only** published ingress — a
   directly-exposed container port would let clients spoof XFF.

### B. Frontend

1. `frontend/js/api.js` (new) — `window.api(path, opts)` fetch wrapper that:
   - Injects `Authorization: Bearer <token>` from `sessionStorage` when present.
   - On 401/403 dispatches `ja:auth-required` so pages can show the login prompt.
   - Token helpers: `setAuthToken(token)`, `getAuthToken()`, `clearAuthToken()`.
   - Loaded on every page alongside `terms.js`.
2. `auth.js` — on `verify-code` success call `setAuthToken(resp.token)`; `register` goes through `api()`.
3. User-scoped calls in `profile.js`, `jobs.js`, `referrals.js`, `search.js` route through `api()`
   and stop sending `email` params (server takes it from the token).
4. `admin.html` / `admin.js` — admin-email OTP login gate: no valid token → login modal
   (send-code/verify-code against the admin email), then all admin fetches via `api()`.
5. `index.html` / `profile.html` — listen for `ja:auth-required`; prompt the OTP login before
   save-job / referral actions.

### C. Tests

- `backend/tests/test_integration.py` + `test_features.py` hit ~85 protected call sites without a
  token and will 401.
- Add `_auth(email)` helper: `verify-code` (DEV_MODE 123456) → token → `Authorization` header; thread
  into the protected call sites. Public-endpoint tests stay unchanged.
- Keep the 7 pre-existing failures as expected until their root causes are addressed.
- **New auth-behavior tests:**
  - Malformed/garbage `Authorization` header (wrong scheme, empty, junk) → **401, not 500**.
  - `OPTIONS` to a protected path → passes through (no auth required).
  - App boot with empty `JWT_SECRET` in non-`DEV_MODE` → raises.
  - `POST /api/auth/register` without a token → 401.
  - `company-counts`: anonymous returns plain counts; with a token, excludes the token email.
  - `/docs`, `/db` without token → 401.
  - `/api/admin/*` with non-admin token → 403; with **lowercased** admin email → 200.

### D. Deploy & verify

1. Snapshot image `job-agent:snapshot-<timestamp>-pre-auth`.
2. **Set `JWT_SECRET` on the server BEFORE shipping any code that reads it** — preferred: env var at
   container start; acceptable: one line appended to the server-side `config.py`. Either way the boot
   fail-fast (Part 3.1) catches omissions. Verify with
   `docker exec job-agent python -c "from config import JWT_SECRET; assert JWT_SECRET"`.
3. `docker cp` backend (`utils/jwt.py`, `api/deps.py`, `api/main.py`, `auth.py`, `profile.py`,
   `saved_jobs.py`, `referrals.py`, `resume.py`, `jobs.py`, `admin.py`, `users.py`, `leads.py`) +
   frontend (`api.js`, `auth.js`, `profile.js`, `jobs.js`, `referrals.js`, `search.js`, `admin.js`,
   `admin.html`, `index.html`, `profile.html`).
4. `docker exec job-agent python -m py_compile <changed files>` → `docker restart job-agent`.
5. **Ingress audit**: confirm nginx is the only published port (no directly-exposed container port
   that would allow XFF spoofing to dodge IP rate limits).
6. Verification matrix (curl):
   - `/health` 200; `/app`, `/js/*` 200 (static stays open)
   - `/api/stats/public` 200 no token
   - `/api/profile` → **401** no token
   - `/api/profile` with token → 200, returns **own** data; token for another user → own data only
   - `/api/users/company-counts` anonymous → plain counts; with token → excludes self
   - `OPTIONS /api/profile` → not 401
   - malformed `Authorization: Basic xyz` → 401, not 500
   - `/db` → 401 no token
   - `/api/admin/stats` → 401 no token; non-admin token → **403**; admin token (any case) → 200
   - `/docs` → 401 no token (admin token → 200)
   - OTP login → token minted; `register` without token → 401

### E. Rollback

- Image snapshot from Step D.1; redeploy the pre-auth snapshot and `docker restart`.

---

## Part 4 — Sequencing

1. Backend foundation: `jwt.py`, `config.JWT_SECRET` + boot fail-fast, `deps.py` strict parser,
   `auth.py` token mint + register gate. (A1–A3)
2. Middleware guard: OPTIONS bypass, whitelist, admin class, lowercase-compare. (A4)
3. Identity swap across user-scoped handlers + `company-counts` optional auth. (A5)
4. Frontend `api.js` + token helpers. (B1)
5. Page wiring: auth.js, profile/jobs/referrals/search, admin gate. (B2–B5)
6. Test updates incl. new auth-behavior tests. (C)
7. Deploy: snapshot → `JWT_SECRET` on server + assert → docker cp → py_compile → restart → ingress
   audit → verification matrix → commit (config.py excluded). (D)

## Part 5 — Open items (resolved)

Both items from the original sweep are now decided; no unresolved waiver remains.

- `/api/users/company-counts` → **optional auth** (`get_optional_user`): token present → exclude the
  token email from counts; anonymous → plain counts. The `user_email` query param is removed
  server-side, closing the opt-in enumeration leak while keeping the funnel's "N here" badge. (Part
  3.5, `users.py`.)
- `/api/referrals/resolve-url` → **stays public** (Part 1). Inbound referral clicks happen before
  login and the endpoint only normalizes a job URL; no personal data, no write side effect worth
  gating.
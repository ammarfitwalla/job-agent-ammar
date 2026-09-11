# JWT Auth — How It Works

JobAwn uses **stateless, signed, expiring tokens (JWT HS256)** for authentication. No passwords,
no server-side sessions, no client-supplied identity. The server trusts only what a signed token says.

---

## Flow (step by step)

### 1. Request a code
User enters their email → frontend calls `POST /api/auth/send-code` (public).

- **Dev** (`JWT_ALLOW_DEV_SECRET`) returns the code `123456` directly.
- **Prod** emails a real 6-digit code via SMTP.

### 2. Verify the code
Frontend calls `POST /api/auth/verify-code` (public) with `{ email, code }`.

### 3. Server mints a token
If the code is valid, the server creates a JWT:

```json
{ "alg": "HS256", "typ": "JWT" }
{ "sub": "<email>", "iat": <now>, "exp": <now + 24h> }
```

Signed with `JWT_SECRET` (from `backend/config.py`) using HMAC-SHA256. Only the server
can create or verify these cards. Response:

```json
{ "ok": true, "token": "...", "user": { "...": "..." } }
```

`/api/auth/verify-code` also auto-creates the user if they don't exist yet.

### 4. Browser stores the token
`frontend/js/auth.js` → `window.setAuthSession(token, email)` stores it in **sessionStorage**
(`ja_token`). Per-tab, cleared when the tab closes.

### 5. Every protected call carries the token
All calls use `window.api(path, opts)` (`frontend/js/api.js`), which automatically adds:

```
Authorization: Bearer <token>
```

Downloads go through `window.downloadAuthed()` (marks links with `data-download="1"`),
because a plain `<a href>` can't send the header.

### 6. Middleware checks every request
`auth_guard` in `backend/api/main.py` reads the header, verifies the signature + expiry,
and extracts the email from `sub`. Then it classifies the path:

| Class | Examples | Requirement |
|---|---|---|
| Public | `/`, `/app`, `/profile`, `/admin`, `/health`, `/js/*`, `/api/auth/send-code`, `/api/auth/verify-code`, `/api/users/at-company`, `/api/referrals/resolve-url`, `/scrape`, `/jobs`, `/roles`, `/states`, `/api/visit/*` | None |
| Protected `/api/*` | `/api/profile`, `/api/saved-jobs`, `/api/referrals/*`, `/api/auth/register`, `/api/auth/companies` (POST), `/roles/custom` | Valid token → else `401` |
| Admin | `/api/admin/*`, `/resume/download`, `/resume/storage`, `/api/leads`, `/api/referrals/notifies`, `/db`, `/logs`, `/docs`, `/redoc`, `/openapi.json` | Valid token **and** email == `ADMIN_EMAIL` → else `401`/`403` |

`OPTIONS` preflights always pass. `/docs` etc. are public **only** when
`JWT_ALLOW_DEV_SECRET=1` is set (dev convenience).

### 7. Routes trust the token, not the client
Endpoints use `Depends(get_current_user)` (`backend/api/deps.py`) to read the identity:

```python
user = Depends(get_current_user)   # user["email"] comes from the token
```

Examples:
- `GET /api/profile` → profile of the token's email (client cannot pass another email).
- `POST /api/auth/register` → email must match the token, else `403`.
- `PATCH /api/saved-jobs/{id}` / `DELETE` → ownership check via `get_saved_job_owner` → `403`.
- Referrals: accept = receiver only, withdraw = sender only.
- Admin routes use `_check_admin(email)` as a second layer.

### 8. Login prompt on 401
Any `401` from `window.api()` fires the `ja:auth-required` event:
- Regular pages → login modal (`auth.js`), debounced 60s.
- Admin page → admin OTP gate (`admin.js`).
- If a token was attached, `api.js` deletes it — a 401 means the token is dead.

### 9. Expiry
Tokens expire after `JWT_ACCESS_TOKEN_MINUTES` (default `1440` = 24h). After that the
backend returns `401` and the user must re-login. **There is no silent auto-refresh yet.**

---

## Key files

| File | Role |
|---|---|
| `backend/config.py` | `JWT_SECRET` (hardcoded, git-ignored), `JWT_ALLOW_DEV_SECRET`, `JWT_ACCESS_TOKEN_MINUTES`, `ADMIN_EMAIL` |
| `backend/utils/jwt.py` | `create_token`, `decode_token`, `ensure_secret` (pure stdlib HS256) |
| `backend/api/deps.py` | `get_current_user`, `get_optional_user` |
| `backend/api/main.py` | `auth_guard` middleware + public/admin/path whitelists |
| `backend/api/routes/*` | Token-scoped endpoints |
| `frontend/js/api.js` | `window.api()` (Bearer header, 401 handling), `downloadAuthed`, session storage |
| `frontend/js/auth.js` | OTP modal + `setAuthSession` |

See also `docs/deployment/jwt_deploy_runbook.md` for production deployment.
# Profile + Saved Jobs + Application Status — Implementation Plan

## Overview

Two linked features that transform the app from a one-shot search tool into a personal job pipeline:

1. **Save jobs** with email-verified profiles
2. **Track application status** per saved job

No cron, no saved search re-scraping — just individual job saving with a lightweight account system.

---

## User Flow

```
User sees a job card ─click bookmark icon─┐
                                          ▼
                              ┌──────────────────────┐
                              │  "Enter your email    │
                              │  to save jobs"        │
                              │  [email input]        │
                              │  [Send Code]          │
                              └──────────────────────┘
                                          │
                                          ▼
                              ┌──────────────────────┐
                              │  Check your inbox     │
                              │  [6-digit code input] │
                              │  [Verify]             │
                              └──────────────────────┘
                                          │
                               ┌─────────┴─────────┐
                               ▼                    ▼
                         ┌──────────┐      ┌──────────────────┐
                         │ Profile  │      │ Job saved        │
                         │ created  │      │ bookmark fills   │
                         └──────────┘      └──────────────────┘

On return visits: email cached in localStorage → no re-auth
User visits /profile.html → sees name, saved jobs, status dropdowns
```

---

## Database Changes (`backend/db.py`)

### New Table: `users`

```sql
CREATE TABLE IF NOT EXISTS users (
    email TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

### New Table: `verification_codes`

```sql
CREATE TABLE IF NOT EXISTS verification_codes (
    email TEXT NOT NULL,
    code TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_vcodes_email ON verification_codes(email);
```

### New Table: `saved_jobs`

```sql
CREATE TABLE IF NOT EXISTS saved_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_email TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    company TEXT DEFAULT '',
    url TEXT DEFAULT '',
    location TEXT DEFAULT '',
    salary TEXT DEFAULT '',
    total_score INTEGER DEFAULT 0,
    ai_score INTEGER DEFAULT 0,
    keyword_score INTEGER DEFAULT 0,
    reason TEXT DEFAULT '',
    experience_level TEXT DEFAULT '',
    tags TEXT DEFAULT '[]',
    site TEXT DEFAULT '',
    application_status TEXT DEFAULT 'saved',
    saved_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_email) REFERENCES users(email)
);
CREATE INDEX IF NOT EXISTS idx_saved_email ON saved_jobs(user_email);
CREATE INDEX IF NOT EXISTS idx_saved_status ON saved_jobs(user_email, application_status);
```

### New DB Functions

| Function | What it does |
|----------|-------------|
| `get_user(email)` | Returns user dict or None |
| `create_user(email, name)` | INSERT user |
| `update_user_name(email, name)` | UPDATE name |
| `save_verification_code(email, code, expires_at)` | INSERT code |
| `verify_code(email, code)` | Check + mark used |
| `add_saved_job(user_email, job_data)` | INSERT saved job |
| `get_saved_jobs(user_email, status=None)` | SELECT, filter by status |
| `update_saved_job_status(job_id, status)` | PATCH application_status |
| `delete_saved_job(job_id)` | DELETE |
| `is_job_saved(user_email, url)` | Boolean check |

---

## New API Endpoints

### Auth Routes — `backend/api/routes/auth.py`

`/api/auth` router — added to `main.py` as `app.include_router(auth.router)`

| Method | Path | Body | Response | Logic |
|--------|------|------|----------|-------|
| `POST` | `/api/auth/send-code` | `{"email": "a@b.com"}` | `{"sent": true}` | Generate 6-digit code, store in DB with 10min expiry, send email via SMTP |
| `POST` | `/api/auth/verify-code` | `{"email": "a@b.com", "code": "123456"}` | `{"ok": true, "user": {email, name}}` | Check code, mark used, create user if first time, return user |

**Email sending:** Reuse `utils/emailer.py` — add a new function `send_verification_code(email, code)` that sends a simple plain-text email with the code. The receiver is dynamic (not `config.EMAIL_TO`).

### Profile Routes — `backend/api/routes/profile.py`

`/api/profile` router

| Method | Path | Body | Response |
|--------|------|------|----------|
| `GET` | `/api/profile` | Query: `?email=x` | `{email, name, created_at}` |
| `PUT` | `/api/profile/name` | `{"email": "x", "name": "Alex"}` | `{email, name}` |

### Saved Jobs Routes — `backend/api/routes/saved_jobs.py`

`/api/saved-jobs` router

| Method | Path | Body / Query | Response |
|--------|------|-------------|----------|
| `POST` | `/api/saved-jobs` | `{"email": "x", "title": "...", "company": "...", "url": "...", ...}` | `{id, saved: true}` |
| `GET` | `/api/saved-jobs` | Query: `?email=x&status=applied` | `[{id, title, company, ...}, ...]` |
| `GET` | `/api/saved-jobs/check` | Query: `?email=x&url=...` | `{saved: true/false}` |
| `PATCH` | `/api/saved-jobs/{id}/status` | `{"status": "interviewing"}` | `{ok: true}` |
| `DELETE` | `/api/saved-jobs/{id}` | — | `{deleted: true}` |

### Emailer Update

Modify `utils/emailer.py`:

```python
def send_verification_code(email: str, code: str):
    """Send 6-digit code to an arbitrary email address using existing SMTP config."""
    # Uses config.EMAIL_USER / EMAIL_PASSWORD
    # Receiver is the `email` parameter (not config.EMAIL_TO)
```

---

## Frontend Changes

### 1. Updated Job Card — `frontend/index.html`

Each card gets a bookmark icon in the top-right corner:

```html
<div class="job-card">
  <div class="flex justify-between">
    <div> ... title, company, scores ... </div>
    <button class="bookmark-btn" onclick="toggleSaveJob(event, jobData)">
      <!-- Empty when not saved (⬡), filled when saved (⬢) -->
      <svg class="bookmark-icon" data-saved="false">...</svg>
    </button>
  </div>
  <div> ... rest of card ... </div>
</div>
```

- **Not saved:** Outline bookmark icon (gray, semi-transparent, shows on hover)
- **Saved:** Filled bookmark icon (blue/indigo)
- Clicking → if user email is cached → toggle save; if not → show auth modal

### 2. Auth Modal — `frontend/index.html`

A modal overlay (hidden by default) with two steps:

**Step 1 — Email entry:**
```
┌──────────────────────────────────┐
│        Save jobs to profile      │
│                                  │
│  Email: [___________________]    │
│                                  │
│         [Send Code]              │
│                                  │
└──────────────────────────────────┘
```

**Step 2 — Code verification:**
```
┌──────────────────────────────────┐
│        Check your inbox          │
│       Code sent to a@b.com       │
│                                  │
│  Code: [____]                    │
│                                  │
│         [Verify]                 │
│                                  │
│  ── or ──                       │
│  [Try another email]             │
└──────────────────────────────────┘
```

On success:
- Store `{email, name}` in `localStorage`
- Close modal
- Execute the save job action that triggered the flow
- Show brief toast: "Job saved! View in Profile →"

### 3. Profile Icon in Header — `frontend/index.html`

In the top bar, next to the tagline or search controls:

```html
<a href="/profile.html" class="profile-link" title="Your Profile">
  <svg>...</svg>  <!-- user icon -->
</a>
```

If user is logged in (email in localStorage), show a filled user icon with a badge.
If not logged in, show an outline icon — clicking opens the auth modal (or navigates to profile page which shows auth).

### 4. Profile Page — `frontend/profile.html`

New HTML page, same styling as `admin.html` (dark header, card layout, same fonts/colors).

**Layout:**

```
┌──────────────────────────────────────────┐
│  ← Back to Search      Profile           │
├──────────────────────────────────────────┤
│                                          │
│  ┌────────────────────────────────────┐  │
│  │  Your Name                         │  │
│  │  [Alex             ✏️]             │  │
│  │  alex@gmail.com                    │  │
│  │  Member since Jun 2026             │  │
│  └────────────────────────────────────┘  │
│                                          │
│  ┌ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐  │
│  │  All (12) | Saved (5) |          │  │
│  │  Applied (3) | Interviewing (2)  │  │
│  │  Offer (0) | Rejected (2)       │  │
│  └ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘  │
│                                          │
│  ┌────────────────────────────────────┐  │
│  │  Senior Dev @ Google       [▼]    │  │
│  │  Saved · Jun 30, 2026             │  │
│  │                                   │  │
│  │  ┌──────────────────────────┐     │  │
│  │  │ Score: 85 ──────────■── │     │  │
│  │  └──────────────────────────┘     │  │
│  │  AI: 45  KW: 40                   │  │
│  └────────────────────────────────────┘  │
│                                          │
│  [More saved jobs...]                     │
│                                          │
└──────────────────────────────────────────┘
```

**Key interactive elements:**
- **Name:** Click pencil icon → inline text input → `PUT /api/profile/name`
- **Status dropdown per job:** `[Saved ▼]` → options: Saved, Applied, Interviewing, Offer, Rejected + Remove
- **Status filter tabs:** Clicking filters the list
- **Job title/company:** Clicking opens the URL in a new tab
- **Back link:** Returns to main page with the search preserved

**State on load:**
1. Read email from `localStorage` → if none, show auth prompt
2. `GET /api/profile?email=x` → populate name
3. `GET /api/saved-jobs?email=x` → populate job list
4. Default name = `email.split('@')[0]` (shown in name field)

### 5. `localStorage` Schema

```javascript
{
  "profile_email": "alex@gmail.com",
  "profile_name": "Alex",
  "profile_saved_at": "2026-06-30T..."
}
```

Checked on every page load. If present, user is considered "logged in" for that session.

---

## Files to Create / Modify

### New Files (4)

| File | Description |
|------|-------------|
| `backend/api/routes/auth.py` | `/api/auth/send-code`, `/api/auth/verify-code` |
| `backend/api/routes/profile.py` | `/api/profile` endpoints |
| `backend/api/routes/saved_jobs.py` | `/api/saved-jobs` CRUD |
| `frontend/profile.html` | Profile page with saved jobs + status management |

### Modified Files (6)

| File | Changes |
|------|---------|
| `backend/db.py` | New tables (`users`, `verification_codes`, `saved_jobs`), new functions |
| `backend/api/main.py` | Register new routers (`auth`, `profile`, `saved-jobs`) |
| `frontend/index.html` | Bookmark icon on job cards, auth modal, profile icon in header |
| `frontend/app.js` | `toggleSaveJob()`, `showAuthModal()`, `sendCode()`, `verifyCode()`, localStorage management |
| `utils/emailer.py` | New `send_verification_code()` function |
| `config.py` / `config.example.py` | No changes needed — existing SMTP config is sufficient |

---

## Implementation Order

```
Phase 1 ─ DB + Auth
  [1] Add tables to init_db() in db.py
  [2] Add DB functions (user CRUD, code CRUD, saved job CRUD)
  [3] Create auth.py (send-code, verify-code endpoints)
  [4] Add send_verification_code() to emailer.py
  [5] Test: curl POST /api/auth/send-code → check email

Phase 2 ─ Saved Jobs API
  [6] Create saved_jobs.py (all CRUD endpoints)
  [7] Create profile.py (get + update name)
  [8] Register all new routers in main.py
  [9] Test: curl all endpoints

Phase 3 ─ Frontend Auth Flow
  [10] Build auth modal in index.html
  [11] Add showAuthModal() / sendCode() / verifyCode() in app.js
  [12] localStorage read/write helpers

Phase 4 ─ Bookmark on Job Cards
  [13] Add bookmark SVG icon to card template in app.js
  [14] Add toggleSaveJob() handler
  [15] Check saved status on load (GET /check)

Phase 5 ─ Profile Page
  [16] Create profile.html (header, name editing, saved jobs, status dropdowns)
  [17] Link profile icon in main page header
  [18] Wire all API calls in profile page JS

Phase 6 ─ Polish
  [19] Toasts for save/verify/error
  [20] Bookmark icon animation (outline → filled)
  [21] Mobile responsiveness for profile page
```

---

## Data Flow Example

### Saving a job for the first time:

```
1. User clicks bookmark on job card
2. app.js: check localStorage for profile_email
3. Not found → showAuthModal()
4. User enters email → POST /api/auth/send-code {email}
5. Backend: generate 6-digit code, store in verification_codes, send email
6. User enters code → POST /api/auth/verify-code {email, code}
7. Backend: check code, create user if new, return {ok: true, user}
8. app.js: store {profile_email, profile_name} in localStorage, close modal
9. app.js: POST /api/saved-jobs {email, title, company, url, ...}
10. Backend: INSERT into saved_jobs, return {id, saved: true}
11. app.js: Update bookmark icon to filled state
```

### Returning user:

```
1. User opens page → localStorage has profile_email
2. On job card load: GET /api/saved-jobs/check?email=x&url=y → {saved: bool}
3. Bookmark icons pre-filled for already-saved jobs
4. Click bookmark → POST /api/saved-jobs or DELETE /api/saved-jobs/{id}
```

---

## Edge Cases & Decisions

| Case | Handling |
|------|----------|
| Email not received | "Resend code" button (60s cooldown), same flow |
| Wrong code entered | Show error, allow retry (up to 5 attempts, then block 5 min) |
| Same job saved twice | `saved_jobs` has UNIQUE(user_email, url) constraint |
| localStorage cleared | User sees auth modal again on save attempt — verify-code will return existing user |
| User deletes all localStorage | Same as above — they verify with same email, get back to their profile |
| Job already saved, status updated | Inline PATCH, no re-auth needed |
| Multiple tabs open | Each tab checks localStorage independently — consistent within tab |
| User icon in header | Show filled icon + badge if logged in; outline icon if not |

# Weekly Re-engagement Email Plan ("Come back to the app")

**Status:** Implemented locally + verified (not yet deployed — no prod changes)
**Decisions (user-confirmed):**
- **Cadence:** Weekly
- **Audience:** Dormant users only (no app visit in 7 days, joined >3 days ago)
- **Content:** Fresh-job highlights from `job_cache` (no LLM cost), simple-nudge fallback
- **Opt-out:** `email_opt_out` flag + signed unsubscribe link

---

## 1. Data layer — `backend/db.py`

- **Migration:** add `email_opt_out INTEGER DEFAULT 0` to `users`
  (guarded `ALTER TABLE`, same pattern as the existing `resume_filename`/`last_login` migrations).
- **New index** in `init_db`:
  `CREATE INDEX IF NOT EXISTS idx_visits_email_time ON visits(user_email, created_at)`
  — `visits` currently has no index on `user_email`/`created_at`; the dormancy query needs it.
- **New helpers:**
  - `set_user_email_opt_out(email: str, opted_out: bool)` — toggle the flag.
  - `get_engagement_recipients(cutoff, min_age_days, limit) -> list[dict]` — users where:
    - `email_opt_out = 0`
    - `created_at < (now - min_age_days)`
    - **last activity** `< cutoff`, where last activity =
      `MAX(visits.created_at)` for that `user_email`
      → fallback `users.last_login`
      → fallback `users.created_at`
    - ordered most-dormant-first, sliced to `LIMIT`.
- **Weekly idempotency** rides the existing unique partial index on
  `email_queue.dedup_key` (index: `idx_email_dedup`, UNIQUE WHERE dedup_key != '')
  — no new state table.

## 2. Email template — `backend/emails/templates.py`

- `_build_html(..., unsubscribe_url: str = "")`: render an optional muted
  unsubscribe link line in the Zone E footer (palette colors only).
  Existing 6 builders unchanged (argument is optional).
- **New builder** `build_engagement(name, jobs, role, location, count, has_resume, unsubscribe_url)`
  → returns `(subject, html, text, "engage_weekly")`.
  - Subject example: `JobAwn — 37 fresh {role} jobs near {city}`
  - Body: greeting + "it's been a while" line, `_info_box` listing top 3 jobs
    (`Title — Company · Location`, all escaped), count line, one-line resume
    reminder when `resume_filename == ''`, single CTA "See fresh jobs" →
    `_url("/app", "engage_weekly")`, `why_line`, unsubscribe link in footer.
- **Fallback builder** `build_engagement_fallback(name, has_resume, unsubscribe_url)` —
  generic nudge when there is no anchor role or no cached jobs;
  CTA to `/app`.
- Constraints (test-enforced): everything escaped, exactly one CTA button,
  palette-only hex (reuse `emails.tokens.PALETTE`).

## 3. Producer — `backend/scheduler.py`

- **New `enqueue_engagement_emails()`** mirroring `enqueue_confirm_reminders()`:
  - Gate on `config.ENGAGEMENT_ENABLED` and `config.MAIL_QUEUE_ENABLED`.
  - Per pass, pull `get_engagement_recipients(cutoff=now-ENGAGEMENT_DORMANT_DAYS, min_age_days=ENGAGEMENT_MIN_AGE_DAYS, limit=ENGAGEMENT_MAX_PER_RUN)`.
  - Per recipient pick an **anchor** as `(role, label, city, state, country)` from
    the **profile alone** (saved searches are not consulted):
    1. `users.position` resolved onto a cached role, plus `city`/`state` for the
       lookup (state appended to the label only when the city doesn't already
       imply it, so we never render "New Delhi, Delhi").
    2. The label is kept even when the role is null — that is what drives the
       location-only email below.
  - **Which of the three emails** a dormant user gets:
    | profile role | profile location | cached jobs | email |
    |---|---|---|---|
    | yes | yes | city → state → country hit | `build_engagement`, labelled with the scope the jobs came from |
    | yes | yes | none at any scope | `build_engagement_fallback` (generic) |
    | yes | no | role in their market | `build_engagement`, no location claim |
    | yes | no | none in their market | `build_engagement_fallback` (generic) |
    | no | yes | not looked up | `build_engagement_location_prompt` — names the location, no role, no counts |
    | no | no | n/a | `build_engagement_fallback` (generic) |

    A role with nothing cached deliberately falls to the **generic** email rather
    than a "go search for it" prompt: we would be inviting them to a search we
    have no data for. The generic email stays strictly generic — no role, no
    location and no numbers, even when the profile has both (asserted in tests).
  - **Role resolution** — `users.position` is free text and `job_cache.role` is
    BINARY-collated, so an exact lookup misses on case alone ("Software
    developer" ≠ "Software Engineer", "Ai Engineer" ≠ "AI Engineer"). The role
    is resolved against the distinct cached-role vocabulary
    (`db.get_cached_roles()`, ~122 rows, read once per pass — no index or
    schema change) in increasing cost: exact → case-insensitive →
    qualifier-stripped ("Backend Developer Intern") → typo/punctuation
    (`difflib` ≥ 0.82, "Software Enginner" → "Software Engineer"). Unresolved
    ("Fresher", "Tester") → no anchor → generic fallback. The email always shows
    the canonical role, never the user's spelling.
  - **Location ladder** — fetch fresh jobs via `get_cached_jobs_aggregate()`
    across `CACHE_SITES_INDIA` / `CACHE_SITES_DEFAULT` for the user's country,
    merge + dedupe by URL, cap at `ENGAGEMENT_MAX_JOBS`, trying scopes
    tightest-first and naming only the scope that actually produced the jobs:
    1. `(role, city, state)` → label = city (+ state)
    2. `(role, state)` (unions the state row with its city rows) → label = state
    3. `(role, country)` → **no location at all** (subject drops "near …")
    4. nothing → generic fallback
    Both rungs 1–2 are already covered by `idx_job_cache_key` /
    `idx_job_cache_country`, so the ladder needs no new index.
  - The headline count is the number of postings we actually hold (deduped, up to
    `ENGAGEMENT_MAX_JOBS`); the list is a 3-item preview followed by
    "…and N more waiting on JobAwn", so the subject and the body reconcile.
  - Resolve the **market** first via `_engagement_country(user)`: profile country
    normalized to ISO-2, else the latest geolocated visit's `country_code` (or
    its `country` name through the same lookup). No signal → no search, generic
    fallback. `get_engagement_recipients()` supplies `visit_country_code` /
    `visit_country` as indexed scalar subqueries, so this costs no extra scan.
  - Render the matching builder and
    `enqueue_email(recipient, subj, html, text, dedup_key=f"engage:{YYYY-WW}:{email}")`.
  - try/except + logging identical to `enqueue_confirm_reminders`.
- **Hook:** call `enqueue_engagement_emails()` in `run_mail_queue()`
  immediately after `enqueue_confirm_reminders()`.
- **Self-limiting:** each weekly window burns through the recipient batch over a
  few passes (drain caps at `MAIL_QUEUE_MAX_PER_RUN`/pass), then dedups to zero
  until the next week.

## 4. Unsubscribe — new `backend/api/routes/email_prefs.py` + `backend/api/main.py`

- **New route** `GET /api/email/unsubscribe?email=<email>&s=<sig>` — public
  (add to `_PUBLIC_EXACT_API` in `api/main.py`).
  - `sig` = HMAC-SHA256 over the email keyed on `JWT_SECRET`
    (reuse `utils.jwt._secret()`; verify with `hmac.compare_digest`).
  - Valid sig → `set_user_email_opt_out(email, True)`, return small
    "You're unsubscribed" confirmation HTML.
  - Invalid sig → 400/404.
- **Link helper** building `https://jobawn.com/api/email/unsubscribe?email=...&s=...`,
  used by the template + signing helper. The signature is base64url HMAC-SHA256
  (padding stripped), so it never contains `=`. Returns `""` if no signing
  secret, so a misconfigured environment degrades to no link instead of a
  broken one.
- **Scope:** opt-out suppresses engagement emails only; transactional emails
  (OTP, welcome, referral request/accept, confirm reminders) still send.

## 5. Config — `config.example.py` (+ local `config.py`, prod config)

```python
ENGAGEMENT_ENABLED = True
ENGAGEMENT_DORMANT_DAYS = 7
ENGAGEMENT_MIN_AGE_DAYS = 3
ENGAGEMENT_MAX_PER_RUN = 20
ENGAGEMENT_CACHE_HOURS_OLD = 168   # weekly cache window
ENGAGEMENT_MAX_JOBS = 30           # fetch cap (render top 3)
```

## 6. Tests — `backend/tests/test_mail_queue.py`, `backend/tests/test_integration.py`

- Template: escaping, exactly one CTA, palette-only hex, non-empty
  subject/text/campaign, unsubscribe link present when passed / absent otherwise.
- Migration: `users.email_opt_out` column exists, default 0.
- Sweep (integration): dormant / recently-visited / opted-out / too-new users
  handled correctly; per-pass cap ≤ `ENGAGEMENT_MAX_PER_RUN`; dedup — no re-send
  in the same week, re-send next week (monkeypatch the date); fallback builder
  used when the cache is empty.
- Unsubscribe: valid sig toggles flag + user excluded from next sweep;
  bad sig rejected.
- **End-to-end harness** `backend/scripts/test_engagement_from_users.py` — every
  case is a row in `users` run through the real producer, with roles, cities,
  states, markets and postings **discovered from the live `job_cache`** (nothing
  about a case is hardcoded except deliberately invalid input: blank fields,
  flags, dates, mangled role strings). The live database is copied to a temp file
  first and the copy's user rows are dropped, so `job_agent.db` is never modified
  and only the test subject is ever eligible. `--send` delivers one real email
  per outcome the matrix can produce.
  `python scripts/test_engagement_from_users.py [--send]`.

## 7. Docs — `docs/planning/EMAIL_DESIGN_SPEC.md`

- Add §5 row for `engage_weekly` (+ fallback variant).
- Unsubscribe-link note in §8.

## 8. Deploy (only after build + explicit GO)

- **Files:** `db.py`, `scheduler.py`, `emails/templates.py`,
  `api/routes/email_prefs.py` (new), `api/main.py`, `config.example.py`,
  prod `config.py` (+ ENGAGEMENT_* keys), tests, `EMAIL_DESIGN_SPEC.md`.
- **Flow:** local full test suite (expect 298+ passing, 6 known pre-existing
  failures) → stage to deploy dir → `scp` → `docker cp` → md5 verify →
  `docker restart job-agent` → verify worker log + queued count →
  send one live smoke mail to the admin address with a dedicated dedup key.
  The signed unsubscribe link only works when generated **in prod**
  (`JWT_SECRET` differs per environment and the route must be live), so the
  click-the-link check happens after deploy, not from the local harness.

## Behavior notes

- **Never claim a location we didn't match.** The location ladder names only
  the cache scope the jobs actually came from; when the data is country-wide
  the subject carries no location at all rather than a vague "your area"
  (removed from the codebase).
- **The profile is the only input.** Saved searches are no longer consulted —
  role and location come from `users.position` / `city` / `state` alone, which
  keeps one obvious source of truth.
- **Fallback is strictly generic** — when there is no usable role (no position,
  or it can't be resolved to a cached role, or we have no market to search) or
  the cache has nothing for that role at any scope, we send the generic "Fresh
  roles are waiting for you" nudge. It never names a role, a location or a count
  even when the profile has both, which is asserted in the tests. Numbers only
  ever come from real cached jobs; we never invent counts or subjects, and never
  trigger a scrape from the email.
- **A location with no role gets its own email.** "JobAwn — Find jobs in
  Bengaluru" points the user at their own location without guessing a role or
  quoting a count — we never looked either up.
- **Role resolution is a lookup, not a guess.** A resolved role is used as a
  cache key and must return real jobs before anything renders, so a wrong match
  costs nothing; the email shows the canonical role name, not the user's
  spelling.
- **Country must be known before we search.** The cache is keyed on ISO-2, but
  `users.country` stores a name ("India") and is empty for most dormant users,
  so `_engagement_country()` resolves the market from the profile country first
  (normalized name → code), then the country the app recorded on the user's most
  recent geolocated visit (the ISO-2 `visits.country_code`, else the name run
  through the same lookup — most visit rows predate that column). With no signal
  anywhere we do **not** guess a market: the user gets the generic nudge. We
  deliberately do not default to a country, so we never present one market's jobs
  as if they were the user's own market.
- Weekly key + "dormant ≥ 7 days" means a still-dormant user is nudged every
  week until they return or opt out — the intended re-engagement loop.
- `cutoff` is based on `visits` activity; users with no visits fall back to
  `last_login` then `created_at`, so signup-only users are also eligible.
- `email_queue` rows are never pruned (known GC follow-up; engagement adds to it).

## Verification record (local, 2026-09-30)

- `python scripts/test_engagement_from_users.py` → **30/30**, all cases driven by
  inserted `users` rows against the real `job_cache` (city hit, city+resume,
  state rung, country rung with no location claim, role+location with no market →
  strictly generic, role only, role cached in another market → generic, location
  only, neither, near-miss typo, unrecognisable role, country as a name, country
  from visit code, country from visit name, opt-out, visited today, account too
  new, same-week dedup, week rollover, per-pass cap, disabled flag, and the four
  unsubscribe-signature checks).
- `pytest tests/test_mail_queue.py` → **53 passed**, 10 subtests.
- `pytest tests/test_integration.py` → **134 passed**.
- The old fixture-driven `scripts/test_engagement_flow.py` was deleted: it
  hardcoded one role and placeholder postings ("Acme Corp"), and two of its cases
  covered the saved-search anchor that no longer exists.
- Real-data read-only simulation against the local snapshot (18 dormant users):
  role resolution fixes all 9 dirty profile spellings, and 16 of the 18 have no
  role **and** no country signal, so generic is the honest outcome for them rather
  than a matching failure.
- Bugs caught during development: profile anchor rendered "New Delhi, Delhi";
  saved-search anchor's location was used for the subject but not the cache
  lookup; `users.country` stored "India" while the cache is keyed "in"; the
  headline count didn't reconcile with the 3-job preview; and the first live sends
  shipped placeholder jobs instead of real cached ones.

## Production deployment - 2026-09-30

Deployed to `ubuntu@130.210.34.176` (container `job-agent`) via `scp -> docker cp -> md5
verify -> docker restart`; see `docs/deployment/deployment_record.md` for the full entry,
rollback paths and per-file table. Migration and route were verified with the feature
**off** first (zero rows in the queue), then enabled.

First run: **16 queued, 16 sent, all `attempts=1`**, every one the strictly generic email.
The cause is data, not matching: only 338 of 1435 `visits` rows carry a `user_email`, and
1097 rows have a country with no `user_email` (captured logged-out, never attributed), so
the dormant cohort has no market and 16/16 correctly fall through to the generic branch.
7 of the 16 have roles that resolve to cached roles with 30 jobs each, blocked purely on the
missing market - the owner accepted the generic send for week 2026-W39. Fixing that means
capturing the market at signup or attributing logged-out visits, which is app-level work
outside this feature.

Post-deploy checks: the next worker pass enqueued nothing (the `engage:{week}:{email}` key
holds - 16 dormant, 0 eligible for the week), zero tracebacks, public `/health` 200 and a
bad-signature unsubscribe 400 verified from off-host, and the signed link stored in the
actually-sent mail validates against the production `JWT_SECRET`.
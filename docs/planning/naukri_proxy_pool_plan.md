# Plan: DB-backed proxy pool for Naukri (and future boards)

## Goal

Stop Naukri scrapes from stalling for minutes on dead proxies. Free proxies
(ProxyScrape) are mostly dead (log: `2/30`–`4/30` working), and today the
scraper **tests up to 30 proxies serially (10s timeout each) inside the
request path** before the first job row: a single Naukri combo took ~117s of
pure proxy probing before any results (`[SCRAPE] AI Engineer @ naukri — Mumbai`
→ jobs at +117s, user cancelled).

Solution: a **scheduler-primed, DB-backed proxy pool** — an always-on
background refresher tests proxies and stores the working ones in sqlite.
On scrape, Naukri draws a batch from the DB and **skips a failing proxy
immediately** instead of waiting on retries. When the batch runs out it refills
from the DB again. The table and helpers are **generic (`board` column)** so
other boards (Indeed/LinkedIn) can reuse them later.

## Decisions (from user Q&A)

- **Dispatcher model — "one-time-use" statuses plus a lease**:
  - Proxy status is exactly `free → in_use → (free | dead)`.
  - A proxy is **claimed (set `in_use`) when a scrape draws it**, so no two
    scrapes can use the same proxy at the same instant.
  - On **success** → released back to `free`. On **fail/406** → `consecutive_fails`
    bumped; `>= 3` → `dead`, else back to `free` (temp cool-off).
  - Missing piece of a pure dispatcher model: a **crashed/cancelled scrape**
    would leave proxies stuck `in_use` forever. So each claim also stamps
    `claimed_until` (lease, ~10 min). A pickup may take **expired-lease**
    `in_use` rows as last resort; a live `in_use` row is never touched.
  - Net: no two scrapes share a proxy at the same instant; crashed runs
    self-heal via the lease; proxies live/die on real evidence.
- **Never go direct**: Naukri requests only ever go out through pool-sourced
  proxies. If the pool is empty, do one inline refresh (blocking) — still no
  direct connection.
- **Always-on refresher thread**, independent of `SCHEDULER_ENABLED` (currently
  `False`), so a warm pool exists even with the main prewarm scheduler off.
- Refresher is **single-owner** across processes via the existing
  `scheduler_lock` leader pattern.
- Table + helpers are **board-generic** from day one (future boards register a
  `PROXY_TESTERS` probe function; nothing else changes).

## Change list

### 1. `backend/db.py` — generic `proxies` table

Add to `init_db` schema (same block as `prewarm_queue`, `db.py:198`):

```
CREATE TABLE IF NOT EXISTS proxies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    board TEXT NOT NULL,                    -- 'naukri' today; 'indeed'/'linkedin' later
    proxy_url TEXT NOT NULL,
    protocol TEXT NOT NULL DEFAULT 'http',
    status TEXT NOT NULL DEFAULT 'free',    -- free / in_use / dead
    source TEXT NOT NULL DEFAULT 'proxyscrape',
    success_count INTEGER NOT NULL DEFAULT 0,
    fail_count INTEGER NOT NULL DEFAULT 0,
    consecutive_fails INTEGER NOT NULL DEFAULT 0,
    tested_at TEXT,
    last_success_at TEXT,
    claimed_until TEXT,
    UNIQUE(board, proxy_url)
);
CREATE INDEX IF NOT EXISTS idx_proxies_pick
    ON proxies(board, status, claimed_until);
```

Helpers (all take `board`, all writes under existing `db._write_lock`, `db.py:12`):
- `upsert_proxy(board, proxy_url, protocol=..., source=..., rekindle=False)` — insert or reset a `dead` row back to `free` on re-test success.
- `claim_proxies(board, n, exclude=None, lease_minutes=10)` — atomically pick `free` rows (fallback: expired-`in_use`), set `in_use` + `claimed_until`; returns the drawn URLs. Returns fewer than `n` if the pool is short.
- `release_proxy(board, proxy_url)` — back to `free`, clear claim (wrapped in `finally` on the scrape side).
- `mark_proxy_fail(board, proxy_url, cooldown_window=60)` — bump `fail_count` + `consecutive_fails`; `>= 3` → `dead`, else `free` with `tested_at` set (temp cool-off).
- `mark_proxy_success(board, proxy_url)` — reset `consecutive_fails`, refresh `last_success_at`, `free`.
- `refresh_pool(board, tested, now)` — prune stale/dead rows, cap table (~30–50 rows/board).
- `proxy_pool_stats(board)` — counts by status (for logs/status endpoint).

### 2. `backend/scheduler.py` — always-on refresher

- New `refresh_proxy_pool(board="naukri")`:
  - Acquire `scheduler_lock` (existing owner/heartbeat pattern, `scheduler.py:144`);
    non-owner exits quietly.
  - Fetch free list (reuse `scrapers.naukri_scraper._fetch_free_proxies`), test up to
    `NAUKRI_PROXY_TEST_LIMIT` (30) with `NAUKRI_PROXY_TEST_TIMEOUT` (5s) using the
    registered tester `PROXY_TESTERS = {"naukri": _proxy_test_naukri}`.
  - `upsert_proxy` for each working one (rekindle if previously `dead`);
    `refresh_pool` prune/cap.
- Start an **always-on daemon thread** at import/app-start (guarded, idempotent),
  **not** gated on `SCHEDULER_ENABLED`. Loop every `NAUKRI_PROXY_REFRESH_MINUTES`
  (15). Uses the single-owner lock so only one process refreshes even with Nakuplus workers
  or prewarm running elsewhere.

### 3. `backend/scrapers/naukri_scraper.py` — skip-fast + refill

- Remove the in-request-path probing (`_PROXY_CACHE`, `_get_working_proxy()` full
  probe on cold cache).
- New per-scrape `_ProxyQueue`:
  - Init: `db.claim_proxies("naukri", NAUKRI_PROXIES_PER_SCRAPE=8)`.
  - `next()`: pop; if empty mid-run → `claim_proxies(..., exclude=tried)` again;
    if still empty → one inline `refresh_proxy_pool()` then one more claim; if
    still empty → raise/abort combo (never go direct).
  - On success → `release_proxy`; on fail/406 → `mark_proxy_fail` + immediately
    try next proxy (**remove the 28s/56s `delay` backoff** in `_search_term`,
    `naukri_scraper.py:251-258`).
  - Wrap acquisition in `try/finally` so a cancelled scrape releases holds.
- Keep `_naukri_location` (`:141`) and the `_warm_up` per-proxy flow.
- Log line per batch: `[NAUKRI] pool: drew 8, used 3, skipped 2, refilled from DB`.

### 4. `backend/config.py`

- `NAUKRI_USE_PROXY = True` (unchanged)
- `NAUKRI_PROXY_REFRESH_MINUTES = 15`
- `NAUKRI_PROXY_TEST_TIMEOUT = 5`
- `NAUKRI_PROXY_TEST_LIMIT = 30`
- `NAUKRI_PROXIES_PER_SCRAPE = 8`
- `NAUKRI_PROXY_CLAIM_MINUTES = 10`
- `NAUKRI_PROXY_POOL_MAX = 50`

### 5. Frontend / API (optional, low priority)

- Expose `proxy_pool_stats(board)` via an admin endpoint (`/admin/proxies`) so
  pool health is visible. Not required for the core fix.

## Validation

1. `python -c "import api.main"` (or run app) → `proxies` table exists;
   `refresh_proxy_pool("naukri")` populates rows on first pass (~30s worst case).
2. `/scrape` for `naukri` @ Mumbai → first rows within ~30s; log shows proxy
   draw/skip/refill; no 28/56s backoff lines; state transitions visible.
3. Re-run `scripts/test_state_cities.py` (sets `NAUKRI_MAX_406_RETRIES=0`) — no
   regression; no direct-connection fallback introduced.
4. Re-run `tests/test_integration.py` + `node --check frontend/js/search.js` if
   frontend touched.
5. Manual: search `AI Engineer` @ Mumbai on the UI → Naukri rows appear without a
   multi-minute freeze.

## Not in scope

- Deploy/push (will only happen on explicit request).
- Changing the free-proxy source (still ProxyScrape).
- Other boards' registration (scaffolding only — `board` + `PROXY_TESTERS` are
  ready but only `naukri` is wired).
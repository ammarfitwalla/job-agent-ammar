# Unique-Job Canonical Store & Per-Job-Location Cache — Plan

Status: Approved for implementation
Date: 2026-09-18

## Problem

The "Jobs Scraped" number is wrong everywhere it's shown because it is derived
from stores that intentionally repeat the same posting:

- Admin `/stats` -> `SUM(scraped) FROM sessions` — counts the same posting once
  per search (per-session dedup only). Locally: **3396**.
- Public `/api/stats/public` -> `SUM(job_count) FROM job_cache` — counts the same
  posting once per combo-cache partition (role x site x city x state x country x
  remote) and only what's currently cached. Locally: **1163**.

The unique-posting count locally is ~**1113** (jobs table distinct URLs **1057**
+ prewarm-only URLs only present in `job_cache` **+56**; the cache is a superset).

Root cause is storage, not counting: no canonical "one row per unique posting"
store exists, and cache rows are keyed by the **searched** location rather than
the **job's own** location.

## Target design

Three changes, all locked:

1. **Canonical `jobs` table** — `url TEXT PRIMARY KEY`. Each posting stored
   exactly once (all fields + enrichment scores + `first_seen`/`last_seen`).
   Fed by both prewarm and sessions. **This is the only store used for counts.**

2. **`job_cache` keyed by the job's own location (from jobspy)** instead of the
   searched location, for ALL sites (currently only Naukri tags per-job
   location; other sites save under the searched combo). Additionally:
   - combo rows keep full `jobs_json` (unchanged serving content model);
   - add a `session_id TEXT DEFAULT ''` column and widen the PK to
     `(role, site, city, state, country, internship_mode, hours_old, is_remote, session_id)`;
   - per-session history receipts live in `job_cache` as rows tagged with
     `session_id`, storing the ordered served URL array (references only — no
     content copies);
   - TTL pruning (`gc_job_cache`) is guarded to combo rows (`session_id = ''`).

### Location bucketing (per-job, write time)

Derived strictly from the job's own `location`/remote fields returned by jobspy:

| Job's reported location            | Cache row key                       |
|------------------------------------|-------------------------------------|
| Remote ("remote", "work from home"…) | `city=""`, `state=""`, `is_remote=1` |
| "Mumbai, Maharashtra, India"       | `Mumbai / Maharashtra / in`       |
| "Maharashtra, India" only          | `- / Maharashtra / in`            |
| "India" / blank / unresolvable     | `- / - / in` (combo-country fallback) |

- **Nothing rolls up** to a broader row on its own. A broad search is served via
  aggregation (below), never by backfilling jobs into broader rows.
- **Never drop** a job: unresolvable/non-remote fall back to the country-level
  row instead of being discarded (differs from today's Naukri behavior).
- Dedup per combo row by URL (append if absent, create the row if missing).
- The same URL may legitimately appear in several combo rows (reference copies
  in the serving cache) — this has no effect on counts, which come from `jobs`.

Reuses existing index infra in `api/routes/scrape.py`: `_build_city_state_map`,
`_STATE_INDEX`, `_city_hit_for`, remote detection (currently Naukri-only, to be
generalized).

### Session history

`set_raw_jobs(sid, jobs)` writes:
1. upsert each job into canonical `jobs` (by URL);
2. upsert the session row in `job_cache` (`session_id=<sid>`, combo fields
   empty) holding the ordered URL array served to that search.

`get_raw_jobs(sid)` reads the session row URL array and resolves content from
canonical `jobs` (preserving order). `jobs.py` API response shape is unchanged.

### Serve + freshness (broad searches = cache hit)

`get_cached_jobs_aggregate` already unions by granularity:
- city search: exact city row;
- state search: `state=<state>` rows (the broad row if any **plus all city
  rows**) — includes all cities in that state;
- country search: all rows for the country.

Freshness becomes **aggregate-based** so broad searches don't re-scrape:
- a state scope is `fresh` when its qualifying rows (state + cities) have a
  recent `scraped_at` (within TTL) and ≥ `min_volume`;
- same for country scope over all of its rows;
- degrade to `stale` (serve + top-up) / `missing` (scrape) as today.

## Counts (single definition everywhere)

```
SELECT COUNT(*) FROM jobs
```

Used by:
- Admin "Jobs Scraped" card (`/api/admin/stats` -> `total_scraped_jobs`)
- Public `/api/stats/public` -> `total_scraped`
- Landing counter `data-key="total_scraped"` (relabel "Jobs Live" → "Jobs
  Discovered")

Admin "Avg Jobs/Session" keeps `sessions.scraped` (per-session served count,
internal ratio only). `sessions.scraped` column remains.

## Files to change

- `backend/db.py` — schema/migration; `set_raw_jobs`, `get_raw_jobs`,
  `save_cache_entry`, `get_cached_jobs_aggregate` freshness, `gc_job_cache`
  guard, new `count_unique_scraped_jobs()` helper.
- `backend/api/routes/scrape.py` — generalize per-job-location tagging to all
  sites; uniform city/state/remote grouping in cache persist section.
- `backend/api/routes/admin.py` — `/stats` count from canonical; admin queries
  (relevant_jobs, top URLs, enriched rows) to canonical/joins.
- `backend/api/routes/stats.py` — `total_scraped` from canonical.
- `frontend/js/admin.js` — cards use `total_scraped_jobs` (+ internal
  `total_jobs_returned` for avg).
- `frontend/landing.html` — relabel "Jobs Live" → "Jobs Discovered".

## Migration (one-time script)

1. Build canonical `jobs` from current `jobs` rows + `job_cache.jobs_json`,
   parsed in Python (NaN-safe — 3 rows contain `NaN`, which SQLite JSON
   functions reject).
2. Rebuild session-history rows in `job_cache` from old `jobs` `session_id`
   rows.
3. Re-tag combo rows by resolving each job's own location into
   `(city, state, country, is_remote)` and re-grouping.
4. Follows the existing db.py ALTER/migrate pattern under `_write_lock`.

## Tests & checks

- Extend `backend/tests/test_job_cache.py` and `test_cache_serve.py`:
  per-job-location grouping for all sites; aggregate-based freshness; session
  rows; NaN handling; pruning guard.
- Backend integration tests.
- `node --check frontend/js/admin.js`; in-memory `compile()` of changed py.
- Read-only prod DB before/after verification of the count.

## Deploy

1. Snapshot: `job-agent:rollback-unique-jobs-2026-09-18`.
2. Ship `db.py`, `scrape.py`, `admin.py`, `stats.py`, `admin.js`,
   `landing.html` to the container.
3. Run migration inside the container (backup DB first).
4. Restart `job-agent`; verify `/health` 200.
5. Verify admin `/api/admin/stats` == public `/api/stats/public` == landing
   counter; sanity-check serve (broad search cache-hit) and history resolution.

## Push

Commit (repo-style message, e.g. "feat: canonical unique-job store, per-job
location cache, aggregate freshness") and push to `origin/main`.
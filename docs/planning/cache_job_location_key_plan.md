# Job Cache: store by Job's Own Location — Plan

Status: Implemented locally (deploy/push pending)
Date: 2026-09-18
Scope: **Storage only.** Counts are intentionally left as-is (deferred to a later step).

## Why

`job_cache` rows are keyed by the **searched** location. A "Data Scientist,
Maharashtra" search saves every returned job under the `- / Maharashtra / in`
row, even jobs actually located in Mumbai/Pune/Thane. We want rows keyed by the
**job's own location** as returned by jobspy.

## Behavior

The same TTL-pruned combo cache, but rows are scoped to the job's real
location, for ALL sites (today only Naukri tags per-job location):

| Job's reported location (jobspy)   | Cache row key                     |
|------------------------------------|-----------------------------------|
| Remote ("remote", "work from home"...)| `city=""`, `state=""`, `is_remote=1` |
| "Mumbai, Maharashtra, India"       | `Mumbai / Maharashtra / in`       |
| "Maharashtra, India" only          | `- / Maharashtra / in`            |
| "India" / blank / unresolvable     | `- / - / in` (combo-country fallback) |

Rules:
- **Never drop** a job: unresolvable/non-remote falls back to the country-level
  row (differs from today's Naukri skip behavior).
- Nothing rolls up to a broader row on its own.
- Dedup per row by URL (append if present / create the row if missing).
- Row content model unchanged (full `jobs_json`, `keep_larger`, upsert on key).
- `touch_prewarm_combo` continues per inserted key so prewarm covers the
  location-scoped row.

## Changes

### `backend/api/routes/scrape.py` — `_scrape_combos` (lines ~415-481)

- Generalize the Naukri per-job-location tagger (lines ~299-366) to **all
  sites**: remote detect; city match via `_build_city_state_map`; state-only via
  `_STATE_INDEX`; else country fallback.
- Replace the Naukri-only distribution branch (423-463) and the "save under
  searched combo" else-branch (464-471) with **uniform grouping by
  `(city, state, is_remote)`** and one `save_cache_entry` per group.

### `backend/db.py` — `get_cached_jobs_aggregate` freshness (lines ~802-803)

- Broad-scope status becomes **aggregate-based**: a state/country search is
  `fresh` when its qualifying rows (state + its cities, or country + all of its
  rows) are recent (within TTL) and ≥ `min_volume` → served as a cache hit
  without re-scraping, even though a broad exact-key row usually won't exist.

## Untouched (deferred / out of scope this step)

- `jobs` table and per-session receipts — unchanged.
- `sessions.scraped`, admin "Jobs Scraped" card, `/api/stats/public`, landing
  counter — all counts stay exactly as computed today.
- `save_cache_entry` / `get_cached_jobs_aggregate` merge/serve mechanics.

## Scenarios (worked example: "Data Scientist", Indeed, India, normal mode)

- **S1 — Search "Maharashtra" returns a Mumbai-located job** (`"Mumbai,
  Maharashtra, India"`) → stored in the **`Mumbai / Maharashtra / in`** row, not
  a `- / Maharashtra / in` row. A later broad "Maharashtra" search serves it via
  aggregation (state scope unions state + all city rows). The state row appears
  only when a posting is actually located `"Maharashtra, India"`.
- **S2 — State-only location** (`"Maharashtra, India"`) → **`- / Maharashtra /
  in`** row (`city=""`).
- **S3 — Country-only / blank / unresolvable location** (`"India"`, "400001") →
  **`- / - / in`** row (combo-country fallback). Never dropped.
- **S4 — Remote posting** (`"Remote"` / `"Work from home"`) → **`- / - / in`
  with `is_remote=1`**, `city=""`, `state=""`.
- **S5 — Same posting re-scraped/prewarmed for the same combo** → resolves to the
  same key; `save_cache_entry` merges and **dedups by URL** → still one copy in
  the row.
- **S6 — Same posting found under two different role searches** ("Data
  Scientist" and "ML Engineer") → two role-scoped rows (`(Data Scientist,
  indeed, Mumbai, …)` and `(ML Engineer, indeed, Mumbai, …)`). Accepted
  residual duplicate; out of scope this step.
- **S7 — Same posting with varied location text** (`"Mumbai, Maharashtra"` vs
  `"Mumbai, IN"`) → normalized to the same canonical city via the token maps
  (`_build_city_state_map`, per country) → **same row**, deduped.
- **S8 — User searches "Mumbai", jobspy returns a Thane posting** → stored in the
  **Thane row**. City searches stay **exact** (`city="Mumbai"` only, db.py:
  787-790) → a "Mumbai" search does **not** serve the Thane job; Thane appears
  under the "Maharashtra" broad search. **Decided: stay exact.**
- **S9 — First-ever "Maharashtra" search (nothing cached)** → live scrape; jobs
  tagged into city rows (S1) and possibly a state row (S2). Next "Maharashtra"
  search → aggregate rows are fresh (recent `scraped_at`, `job_count ≥
  min_volume`) → **cache hit**, no re-scrape (aggregate-freshness change).
- **S10 — Prewarm scheduler pass on the same combos** → same tagging path; jobs
  land in the same location-keyed rows; `touch_prewarm_combo` records each
  inserted key.
- **S11 — Foreign / unmatched city in location** while searching India →
  indexes are built for the **combo country**; match resolves to that entry
  (e.g. `Bengaluru / Karnataka / in`) if possible, else falls back to the
  country row (S3). No cross-country guessing.

## Tests & checks

- Update `backend/tests/test_job_cache.py` and `test_cache_serve.py`: uniform
  location grouping for non-Naukri sites; remote/country-fallback rows;
  aggregate-based freshness for broad scopes.
- Run backend tests; in-memory `compile()` of `scrape.py` and `db.py`.

## Deploy

1. Snapshot: `job-agent:rollback-cache-location-key-2026-09-18`.
2. Ship `backend/api/routes/scrape.py`, `backend/db.py` to the container.
3. Restart `job-agent`; verify `/health` 200.
4. Sanity: a state-level scrape populates city rows (not the state row); a
   broad search serves from aggregated city rows as a cache hit.

## Push

Commit (repo-style message, e.g. "feat: cache jobs by job's own location") and
push to `origin/main`.

## Follow-up (separate step)

Fix the displayed "Jobs Scraped"/"Jobs Discovered" count (currently
admin=`SUM(scraped)`/sessions, landing=`SUM(job_count)`/cache) to a single
query-time distinct-URL definition across `jobs` + `job_cache` (~1113 locally),
or a future canonical `jobs` table.
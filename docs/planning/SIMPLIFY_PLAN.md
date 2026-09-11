# Simplify Plan — Remove Scoring Pipeline, Keep Raw Jobs

## Core Idea

Both tabs work identically:
1. Build a role list (Tab 1: user-typed, Tab 2: AI-suggested from resume)
2. For each role → scrape all sites → title-filter → keyword-sort → display max ~30
3. No AI scoring pipeline, no score badges, no blur/unlock gates
4. Future "Check Relevance" button (phase 2) will call the old scoring per-job

---

## Phase 1 — Backend

### `schemas.py`
- Remove `direct_mode` from `ScrapeRequest` (all scrapes are direct now)
- Remove `min_relevant`, `max_passes`, `resume_text`, `original_resume`
- Simplify to: `sites`, `roles`, `search_id`, `location`, `keywords`, `internship_mode`, country params, `user_email`

### `scrape.py`
- **Remove `run_scrape()` entirely** — this was the scoring pipeline (scrape → score batches → relevance engine)
- **Rename `_scrape_direct` → `run_scrape`** — this is the only scrape path now
- Remove scoring-related log patterns (`[SCORE]`, `[MATCH ENGINE]`)
- Remove `set_filtered_jobs`/`add_filtered_job`/`count_filtered_jobs` calls
- Keep: scrape sites → title filter → keyword-sort → store via `set_raw_jobs`
- The route handler calls `run_scrape()` directly in a thread

### `jobs.py`
- Remove `raw` query param from `GET /jobs` — always returns whatever was stored
- Remove `get_total_score()` / scoring aggregation

### `db.py`
- Add `# DEPRECATED — preserved for future per-job scoring` comments on:
  - `set_filtered_jobs`
  - `add_filtered_job`
  - `count_filtered_jobs`
  - `get_filtered_jobs`
  - `get_events` (still used for logs but simplify to remove scoring event types)

### `config.py`
- Remove `COMPANIES` if unused, or leave as-is

### `relevance_engine.py`
- **Untouched** — preserved for future "Check Relevance" button

---

## Phase 2 — Frontend

### `search.js` — Remove all scoring/blur/vote/lock logic

**State variables to remove:**
- `voteCount`, `voteThreshold`, `showApplyFilters`
- `lastFilteredGen`, `lastPassNum`
- `showingAllResults` (or rename away)

**Functions to remove/simplify:**
- `handleVote()` — remove entirely
- `applyThreshold()` → simplify: just call `renderActiveTab()` (tabs) or `renderJobs()` (single-tab)
- `renderFilterBar()` — simplify or remove (no filters needed beyond sub-filters)
- `countRelevantJobs()` — not needed

**Job card HTML (in `renderJobs`):**
- Remove score badge (the `sc >= 85` / `sc >= 60` / else block)
- Remove score progress bar
- Remove `total_score` reference
- Keep: title, company, location, salary, posted date, experience level, tags, site icon, save/referral buttons

**Job card HTML (in `renderCustomJobs`):**
- Already no score badge — keep as-is (raw card)

**Poll simplification:**
- `pollResults()` (single-tab): Remove `last_scrape_relevant`, `filtered_gen`, `genChanged`, `countChanged` logic. Just show recent job count.
- `pollAIScrape()`: Remove `last_scrape_relevant` check. Just fetch and display.
- Remove `loadResultsIncremental()` — merge into `loadResults()` if needed

### `index.html`
- Remove scoring-related card elements if any exist in static HTML
- Remove any vote/unlock UI

---

## Phase 3 — Timeline Fix

### Custom tab timeline
- Each role's logs rendered separately within its sub-filter section
- Or: logs aggregated by site+role combination with per-role breakdown

### AI tab timeline
- Single scrape session, so the timeline works correctly as-is (no dedup issue)

### Single-tab timeline
- Also single session — works correctly

---

## Order of Execution

1. `schemas.py` — simplify request model
2. `scrape.py` — remove `run_scrape`, rename `_scrape_direct` → `run_scrape`
3. `jobs.py` — remove `raw` param
4. `db.py` — mark scoring functions deprecated
5. `search.js` — remove scoring/blur/vote logic
6. `search.js` — simplify render cards
7. `search.js` — simplify polls
8. `search.js` — fix timeline dedup
9. `index.html` — clean up
10. Verify syntax + walk through all modes

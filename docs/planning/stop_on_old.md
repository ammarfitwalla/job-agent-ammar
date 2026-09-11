# Plan: "Stop on Old" — Incremental Prewarm / Cache Refresh

## Problem

`save_cache_entry` merges by URL (append-only) but the scrape re-pulls the full
page set on every refresh.  A refresh that only adds ~10 new jobs still
re-scrapes all ~30 hits, because there is no signal to stop once we hit jobs
that are already in the DB.

## Goal (confirmed choices)

- Seed the scrape with the combo's **existing cached URL set** -- any URL
  already in the DB is **old**.
- Scrapers return results newest-first; **stop the combo as soon as a batch
  yields only already-cached jobs** (URL-based boundary).  Only genuinely new
  jobs get inserted.
- Lives inside the **shared combo loop** (`_scrape_combos`) so both **prewarm**
  and **live refresh** benefit.
- Behaviour is opt-in (`stop_on_seen=False` by default) so cold first-time
  searches are unaffected.

---

## Files Touched

| File | Change |
|---|---|
| `backend/db.py` | New read-only `get_cache_entry_urls(...)` helper |
| `backend/api/routes/scrape.py` | Pre-seed `seen` from cached entry; add "stop-on-seen" boundary check in `_scrape_combos`; wire `run_scrape` |
| `backend/scheduler.py` | Pass cached URL set + `stop_on_seen=True` into the prewarm `_scrape_combos` call |
| `backend/tests/test_job_cache.py` | New cases for `get_cache_entry_urls` |
| `backend/tests/test_scrape_controls.py` | New cases for boundary-stop logic |

---

## 1.  `db.py` -- seed URL helper

```python
def get_cache_entry_urls(role, site, city, state, country,
                         internship_mode, hours_old, is_remote=0) -> set:
```

Returns the **set of job URL strings** stored in the combo's cache entry.
Uses the same `_cache_key(...)` + `_get_conn()` read path as `get_cache_entry`
but does **no writes**.  Returns `set()` when the entry does not exist.

Read-only; no locking needed (SQLite concurrent read safety).

---

## 2.  `_scrape_combos` -- stop-on-seen (shared loop)

### New opt-in parameter

```python
def _scrape_combos(..., stop_on_seen=False):
```

Default `False` keeps all existing behaviour unchanged.

### Per-combo seeding (after cancel check, before scraper call)

When `stop_on_seen=True` and a cache entry exists, load its URL set and assign
it to a **per-combo local** `old_urls: set` (not merged into `seen` -- `seen`
is the session-level dedup; `old_urls` is the "stop boundary" reference).

```python
old_urls = set()
if stop_on_seen and site_key in SITE_MAP:
    from db import get_cache_entry_urls
    old_urls = get_cache_entry_urls(
        role, site_key,
        combo.get("city") or default_loc, combo.get("state") or "",
        combo.get("country") or "",
        1 if internship_mode else 0, hours_old,
    )
consec_all_old = 0
```

### Boundary check in the dedup block (after `new_count` is computed)

```python
# After: new_count = ... (lines 362-369)
if stop_on_seen and old_urls:
    all_cached = all(
        (j.get("url") or f"{j.get('title','')}{j.get('company','')}") in old_urls
        for j in filtered
    )
    if new_count == 0 and all_cached and filtered:
        consec_all_old += 1
    else:
        consec_all_old = 0

    if consec_all_old >= 2:
        log(f"[SCRAPE] Boundary reached — remaining posts already cached "
            f"for {role} @ {site_key}, stopping combo", sid)
        enough = True
        break
```

### Rules

| Batch content | `consec_all_old` | Behaviour |
|---|---|---|
| ≥1 genuinely new job | reset to 0 | continue scraping |
| all old, first such batch | increment to 1 | keep going (single stale batch is not enough) |
| all old, second consecutive | increment to 2 → **stop** | `enough=True`; break batch + runs loops |

The **"streak of 2"** guard prevents a single mixed page from triggering a
false stop; it only fires once **two consecutive batches** contain zero new
URLs.

### Interaction with max_jobs tail-truncation

`save_cache_entry(..., max_jobs=CACHE_MAX_JOBS_PER_ENTRY=500)` keeps the
**last** (newest) `max_jobs` jobs when the entry exceeds the cap
(`db.py:547-548`).  Verified ordering: `merged` is built existing-then-new
(Python dicts preserve insertion order), so the tail is the newest; the cap
drops the **oldest** and keeps the newest.  Consequences for `stop_on_old`:

- The persisted URL set = the **most recent** `max_jobs` jobs for that combo
  (correct boundary set for "stop on old": these are the ones we've seen).
- Live search writes at `CACHE_MAX_JOBS_PER_ENTRY = 500`; prewarm fetches
  only `CACHE_PREWARM_LIMIT = 30` per pass, so the 500 cap is rarely reached
  by prewarm alone.
- Only residual edge: a job that was **evicted at the cap** (very old) and
  later **resurfaces** (repost/same URL) is not in the cached URL set, so the
  boundary wouldn't recognise it on that pass. Low-probability; self-corrects
  (it just gets re-inserted). Accepted.

No correctness issue: anything genuinely new still gets inserted; we just
don't bail early on evicted-then-resurfaced entries. No code change required
(Option A).

---

## 3.  `scheduler.py` -- wire prewarm to seed + stop

In `_run_workers`, worker function (line ~238), before the `_scrape_combos`
call:

```python
old_urls = get_cache_entry_urls(
    combo["role"], combo["site"], combo.get("city", ""),
    combo.get("state", ""), combo.get("country", ""),
    combo["internship_mode"], combo["hours_old"],
)
_scrape_combos(
    None, [combo],
    keywords=[], internship_mode=combo["internship_mode"],
    hours_old=combo["hours_old"],
    scrape_limit=config.CACHE_PREWARM_LIMIT,
    stagger=(0, 0),
    stop_on_seen=True,
    seen_urls=old_urls,   # seed session dedup AND stop boundary
)
```

`run_prewarm()` itself is unaffected -- its `get_cache_entry` "fresh/stale"
gating stays as-is.

---

## 4.  `run_scrape` -- live refresh path

Inside `run_scrape`, after combos are resolved and `initial_jobs` are loaded
from cache, for each combo whose cache entry was served as "stale" or
"fresh":

```python
_stop_on_seen = bool(initial_jobs)
```

Pass `stop_on_seen=_stop_on_seen` and `seen_urls=seen_urls` into
`_scrape_combos(...)`.  Cold combos (no cache entry) keep current behaviour
(`stop_on_seen=False`).

---

## 5.  Tests

### `db.py` -- `get_cache_entry_urls`
- Returns correct URL set for an existing entry.
- Returns `set()` when entry is missing.
- Handles corrupted `jobs_json` gracefully (returns `set()`).

### `_scrape_combos` boundary stop
- **Boundary fires:** 3 batches where batch 1 + 2 are new, batch 3 + 4 are
  all-old → stops after 2 consecutive old batches (assert final count = new
  ones only, "Boundary reached" log present, batch 4 never consumed).
- **Mixed batch continues:** batch with both new + old → `consec_all_old`
  resets to 0; all new jobs inserted.
- **`stop_on_seen=False`:** existing full-scan behaviour (no boundary stop,
  all batches consumed).
- **No old_urls (cold combo):** `old_urls` is empty → boundary check skipped
  entirely.

### Prewarm worker
- `_run_workers` passes `stop_on_seen=True` and `seen_urls` to
  `_scrape_combos` (assert via a fake `SITE_MAP` capturing kwargs).

### Regression
- `test_scrape_controls.py` (4) + `test_job_cache.py` + `test_pii.py` +
  `test_yoe_bucket.py` pass; `node --check` clean.

---

## 6.  Deploy & verify (on your go)

1. `scp` `db.py`, `scrape.py`, `scheduler.py`, tests to host.
2. `docker cp` → `job-agent:/app/backend/...` for each.
3. `docker restart job-agent`.
4. Verify `/health` 200.
5. In-container smoke: fake combo with 5 existing URLs → scrape returns 7
   jobs (5 old + 2 new) → assert boundary fires after batch hits old URLs
   and only 2 new jobs appear in cache.
6. Commit + push.  **Never stage `config.py` / `tmp_usage.json`.**

---

## Trade-offs Accepted

| Acceptance | Notes |
|---|---|
| Newest-first heuristic | On sites that don't order strictly new→old, we either over-run (safe, just redundant) or stop slightly early (edge case, rarely hit). |
| max_jobs can keep combos refreshing | High-volume entries that exceed the cap won't see the boundary -- bounded by `CACHE_PREWARM_LIMIT` per pass; acceptable. |
| 2-batch streak minimum | Single stale batch doesn't trigger stop; prevents false stops on mixed-yield scrapers. |

---

## Follow-ups (not in this pass)

- Add a persisted per-combo `last_seen_job_at` column to enable age-based
  stop independent of URL ordering.
- Review `max_jobs` truncation to preserve newest-first ordering or cap by
  `posted_at` window instead of tail-trim.

# Country State Fan-Out Cache Plan

## Goal

When a user searches a country without naming a state, evaluate the country scope
**plus its five highest-volume states** instead of trusting the country aggregate row.
Serve everything already cached, refresh every stale or missing state, merge by job
URL, and report coverage in the API response.

Scope: the 38 countries in `backend/api/routes/states.py::COMMON_COUNTRIES`.

## Why

Live probes confirmed that a country-wide query systematically misses jobs that
state-scoped queries find:

| Country | Roles | Country unique | 5-state union | Coverage | Missed |
|---|---|---|---|---|---|
| Saudi Arabia | Data Analyst, Business Intelligence Analyst | 21 | 16 | 131% | 3 |
| India | Data Analyst, Business Intelligence Analyst | 152 | 351 | **43.3%** | 268 |

India is the clear case: the country query returned 152 unique jobs while the five
states returned 351, i.e. 268 jobs the country search never saw. Causes were
ranking/pagination differences plus a missing `Saudi Arabia` subdivision token on
LinkedIn.

The existing cache read already unions country + state + city rows
(`get_cached_jobs_aggregate`), but the **country aggregate freshness flag uses ANY
semantics**: one fresh child row marks the entire country fresh. So a country can
report `done` from cache while four of its five states were never populated.

## Non-goals

- No eager 60-country grid. A full grid is ~43,200 combos (~4,000/day, 10.8-day
  refresh cycle, ~150 serialized hours for LinkedIn alone) and cannot hold a 12h TTL.
- No frontend coverage indicator. API only.
- No change to remote-job handling. Cache reads default to `is_remote=0`.

## Design

### 1. `CACHE_TOP_STATES` config

New hand-curated mapping in `backend/config.py`, mirrored in `config.example.py`:

```python
CACHE_TOP_STATES: dict[str, list[str]] = {
    "sa": ["Riyadh", "Makkah", "Eastern Province", "Al Madinah", "Asir"],
    ...
}
```

Values are canonical `countrystatecity` state names, **not** the names boards display.
Every entry must satisfy:

1. **Resolves canonically** via `get_states_of_country(iso2)`. Verified traps:
   Saudi `Al Madinah` (not `Madinah`), Japan `Ōsaka`, Turkey `İstanbul`,
   France `Île-de-France` / `Grand-Est` / `Provence-Alpes-Côte-d’Azur`
   (curly apostrophe), Denmark `Denmark` (not `Capital Region`),
   Finland uses English names (`Finland Proper`, not `Varsinais-Suomi`),
   Philippines `National Capital Region (Metro Manila)`,
   Switzerland `Zürich`, Sweden `Östergötland`, GB has cities not counties
   (`London`/`Leeds` exist, `West Yorkshire` does not).
2. **No trailing whitespace.** Upstream carries it on `Brussels-Capital ` and
   `Luxembourg `; config stores the stripped name.

Enforced by a test, not by convention.

### 1b. City lists are NOT required for all countries

`CACHE_STATE_CITIES` is read in exactly two places (`scrape.py:209` and
`scrape.py:554`), and **both are gated on `site == "naukri"`**. Naukri is
India-only (`CACHE_SITES_INDIA`, `CACHE_SITES_DEFAULT`). So the city-list
invariant applies to India alone, and India's five curated states already have
entries. Adding city lists for the other 33 countries would be dead config.

Worse, `_build_city_state_map` merges every country's cities into one
country-agnostic `{city: (city, state)}` map, and `_tag_job_location` matches it
by bare substring before the country-filtered `_STATE_INDEX`. Adding non-Indian
cities would inject cross-country false matches, e.g. a US job in "Salem,
Oregon" tagging as Salem/Tamil Nadu. Left India-only deliberately.

### 2. Per-state evaluation in `_cache_lookup`

Replace the country-only shortcut with a loop over `[country_exact] + top_states`.
For each scope call
`get_cached_jobs_aggregate(role, site, "", state, country, ...)`, which at that
granularity leaves `city` unconstrained (`db.py:878-881`) so each state unions its
own row plus its city rows.

| Per-state status | `initial_jobs` | `combos_to_scrape` |
|---|---|---|
| `fresh` | serve | no |
| `stale` | serve (top-up) | yes |
| `missing` | — | yes |

**Freshness refinement:** treat a state fresh only when `status == "fresh"` **and**
`entry["job_count"] >= CACHE_MIN_VOLUME`. Otherwise several sub-threshold rows can
union to >=10 and masquerade as fresh.

Never derive this from the country aggregate (`db.py:889` ANY semantics).

### 3. Coverage-complete gate

`trigger_scrape` takes the `"Served from cache"` branch whenever `combos_to_scrape`
is empty (`scrape.py:1040-1050`). That condition must additionally require all five
states fresh. Mirrors the existing Naukri per-city precedent
(`scrape.py:552-601`), which already serves-fresh / queues-stale-and-missing per child.

### 4. Coverage metadata

`_cache_lookup` returns `CACHE_TOP_STATES_COVERAGE`:

```json
{"states_total": 5, "states_fresh": 3, "states_stale": 1,
 "states_missing": 1, "complete": false}
```

Surfaced on the trigger response. No frontend change.

### 5. Fix `_INDEED_COUNTRY` first

`backend/scheduler.py:20` maps only `in/us/ie/ae` and silently defaults every other
country to `"USA"`. Fan-out across 40 countries would send Indeed to the US site for
36 of them. Replace with the `_COUNTRY_CODE_TO_NAME` lookup that `scrape.py:688`
already builds.

### 6. Warmth for free

New combos flow into `custom_prewarm` via `upsert_custom_prewarm()`; `run_prewarm`
refreshes them; `gc_custom_prewarm(max_age_days=30)` (`db.py:1138`) drops markets
nobody searched. No grid needed.

### 7. Accepted behaviour

- Scrape **all** stale/missing scopes on every country search. No early stop, no cap.
- Thin markets below `CACHE_MIN_VOLUME=10` re-scrape each pass. Churn accepted.
- Worst case 6 scopes x 2 boards = 12 sequential scrapes at `stagger=(1,3)`
  (~2-6 min), mitigated by progressive `set_raw_jobs`. Cross-scope dedup already
  exists in `run_scrape` (`scrape.py:451-459`).

## Implementation order

1. `backend/config.py` + `config.example.py`: `CACHE_TOP_STATES` (38 countries x 5).
2. `backend/scheduler.py`: dynamic Indeed country name resolution.
3. `backend/api/routes/scrape.py`: per-state `_cache_lookup`, coverage metadata,
   complete gate, `custom_prewarm` registration.
4. `backend/tests/`: targeted tests.
5. Re-run the India probe; country-scope unique should rise toward 351.

## Tests

- fan-out fires only for country-only requests; state/city requests unchanged
- mixed per-state statuses serve fresh and queue exactly stale + missing
- country aggregate `fresh` with missing states still triggers scrapes (the
  regression this plan exists to prevent)
- cache-only branch requires all-states-fresh
- no duplicate URLs across country + 5 states
- every curated name resolves canonically, is stripped, and has no duplicates
- exactly 5 states per country, and every key is in `COMMON_COUNTRIES`
- India-only curated states keep their `CACHE_STATE_CITIES` entries
- Indeed `country_indeed` correct for a country outside `in/us/ie/ae`

## Risks

- Hand-curated drift across 190 names — the resolution test catches it, does not
  prevent it.
- Curated ranking can miss real volume (Haryana ranked 4th live at 66 jobs).
- Thin-market churn consumes prewarm budget on low-value states.
- Remote jobs excluded from all reads, unchanged.

### Found while validating: city-labelled markets cannot fill a state cell

`_scrape_combos` files each job under the state resolved from the board's **own**
location text (`_tag_job_location`), not the scope that was searched. `_tag_job_location`
can only reach a state when that canonical state name appears in the text:

| Posted location | Resolved state |
|---|---|
| `Riyadh, Saudi Arabia` | Riyadh |
| `Jeddah, Makkah, Saudi Arabia` | Makkah |
| `Dammam, Eastern Province, Saudi Arabia` | Eastern Province |
| `Buraydah, Al-Qassim, Saudi Arabia` | Al-Qassim |
| `Madinah, Saudi Arabia` | *(country row)* |
| `Abha, Saudi Arabia` | *(country row)* |

India is unaffected (LinkedIn reports `Bengaluru, Karnataka`), which is why the
India probe is the acceptance case. In Saudi-style markets most major cities
report city + country with no state token, so their state cache cells stay empty,
the scope reports `missing`, and the fan-out re-scrapes it on every country
search. Results are still correct (those jobs land in the country-exact row and
are deduped), but cost rises to ~6 scrapes per search.

Follow-up, if the Saudi re-scraping matters: add curated city lists for the top
states so city-labelled postings can resolve to a state. `_build_city_state_map`
has already been scoped by country (see below), so adding lists is now safe.

### Fixed while validating: cross-country city mis-filing

`_build_city_state_map` took a `country_code`, cached per code, and then built
the **identical global map for every country**, matched by bare substring before
the country-filtered `_STATE_INDEX`. So it was already mis-filing:

```
Salem, Oregon, United States  ->  city=Salem, state=Tamil Nadu
```

That US job was written to `job_cache` with `state="Tamil Nadu"` and
`country="us"`. Now filtered to states whose `_STATE_INDEX.country_code` matches
the searched country, with an unfiltered fallback when the index is unavailable
and states it cannot attribute being skipped.

The country is never inferred from the job text — `scrape.py:373` takes it from
the search combo — so scoping by country is sufficient to keep the pairing
honest. `Pune` resolves to Pune/Maharashtra when searching India and falls
through to the country row when searching the US.

Known residue: the map is keyed by lowercase city, so a city listed under two
states (Faridabad, Gurugram in Delhi+Haryana; Noida in Delhi+UP; Udaipur in
Rajasthan+Tripura) collapses to whichever state is seen last. Pre-existing, and
it needs a tie-break policy rather than a scope fix.

## Validation metric

India currently `C=152` vs `U=351` (43.3% coverage). After fan-out, country-scope
unique should rise toward 351. That delta is the acceptance criterion.

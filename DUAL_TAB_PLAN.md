# Dual-Tab Job Display — Implementation Plan

## Overview

When a user searches with custom roles (typed manually), results split into two tabs:

1. **Custom Jobs** — Raw scrape results, sorted by keyword score only. No AI scoring, no AI note. Shows exactly what the user asked for.
2. **AI Recommended** — AI-suggested roles + any AI-selected roles. Full AI + keyword scoring as today.

Tabs appear whenever `customRoles.length > 0`. If no custom roles are selected, current single-list behavior applies unchanged.

---

## Display Rules

| Custom roles selected | AI roles selected | Display |
|---|---|---|
| 0 | 0 | No search (need ≥1 role) |
| 0 | 1+ | No tabs — current behavior (single scored list) |
| 1+ | 0 | Tabs — Custom Jobs (keyword-sorted) + AI Recommended (scored) |
| 1+ | 1+ | Tabs — Custom Jobs (keyword-sorted) + AI Recommended (scored) |

**Rule:** Tabs = custom roles exist. Period. Any AI-selected roles expand Tab 2's scope but don't suppress tabs.

---

## User Flow

```
User clicks "Start Search"
  │
  ├── Classify roles:
  │     customRoles  = typed/selected roles NOT in AI suggestions
  │     aiRoleList   = suggested_roles from keyword extraction + any AI-selected roles
  │
  ├── if (customRoles.length > 0):
  │     │
  │     ├── Show tab bar: [Custom Jobs (N)] [AI Recommended (M)]
  │     │
  │     ├── Tab 1: Fire one scrape per custom role (direct_mode, no scoring)
  │     │     searchIds_custom = [sid1, sid2, sid3]
  │     │     Each returns raw jobs → aggregated into Tab 1
  │     │
  │     ├── Tab 2: Fire one scrape for all AI roles (normal scored)
  │     │     searchIds_ai = [sid4]
  │     │     Returns scored jobs → displayed in Tab 2
  │     │
  │     └── Poll all searchIds, render per active tab
  │
  └── else:
        └── Current behavior (single scrape, scored, no tabs)
```

---

## Phase 1: Backend — Direct Scrape Mode

### 1a. `backend/api/schemas.py`

Add one field to `ScrapeRequest` (line 47):

```python
direct_mode: bool = False
```

No other schema changes.

### 1b. `backend/db.py`

Add three new functions after `get_filtered_jobs()` (~line 421):

#### `set_raw_jobs(sid, jobs)`

Stores raw (unscored) jobs for a session. Same structure as `set_filtered_jobs()` but with `is_raw=1` and all score fields as `None`.

```python
def set_raw_jobs(sid: str, jobs: list):
    with _write_lock:
        with _get_conn() as (conn, cur):
            cur.execute("DELETE FROM jobs WHERE session_id = ? AND is_raw = 1", (sid,))
            rows = []
            for job in jobs:
                rows.append({
                    "session_id": sid,
                    "title": job.get("title", ""),
                    "company": job.get("company", ""),
                    "location": job.get("location", ""),
                    "url": job.get("url", ""),
                    "description": job.get("description", ""),
                    "tags": json.dumps(job.get("tags", [])),
                    "ai_score": None,
                    "keyword_score": job.get("keyword_score"),
                    "total_score": None,
                    "reason": "",
                    "salary": job.get("salary"),
                    "experience_level": job.get("experience_level"),
                    "is_raw": 1,
                    "date_posted": job.get("posted_at", job.get("date_posted", "")),
                    "company_url": job.get("company_url", ""),
                    "job_level": job.get("job_level", ""),
                    "created_at": _now(),
                })
            if rows:
                cur.executemany("""INSERT INTO jobs
                    (session_id, title, company, location, url, description, tags,
                     ai_score, keyword_score, total_score, reason, salary,
                     experience_level, is_raw, date_posted, company_url, job_level, created_at)
                    VALUES (:session_id, :title, :company, :location, :url, :description, :tags,
                            :ai_score, :keyword_score, :total_score, :reason, :salary,
                            :experience_level, :is_raw, :date_posted, :company_url, :job_level, :created_at)""", rows)
            conn.commit()
```

#### `get_raw_jobs(sid)`

Retrieves raw jobs sorted by most recent first.

```python
def get_raw_jobs(sid: str) -> list[dict]:
    with _get_conn() as (conn, cur):
        cur.execute(
            "SELECT * FROM jobs WHERE session_id = ? AND is_raw = 1 "
            "ORDER BY CASE WHEN date_posted = '' THEN 1 ELSE 0 END, date_posted DESC, created_at DESC",
            (sid,))
        rows = cur.fetchall()
        jobs = []
        for row in rows:
            d = dict(row)
            try:
                d["tags"] = json.loads(d["tags"])
            except (json.JSONDecodeError, TypeError):
                d["tags"] = []
            del d["id"]
            del d["session_id"]
            del d["is_raw"]
            del d["created_at"]
            jobs.append(d)
        return jobs
```

#### `count_raw_jobs(sid)`

```python
def count_raw_jobs(sid: str) -> int:
    with _get_conn() as (conn, cur):
        cur.execute("SELECT COUNT(*) FROM jobs WHERE session_id = ? AND is_raw = 1", (sid,))
        return cur.fetchone()[0]
```

### 1c. `backend/api/routes/scrape.py`

#### Add `_scrape_direct()` function (after `_scrape_internship`, ~line 389)

```python
def _scrape_direct(sid, sites, roles, location, adzuna_country, indeed_country,
                   internship_mode=False, user_email=""):
    """
    Scrape-only pipeline. No AI scoring.
    Runs the same scraper dispatch as _scrape_normal.
    Stores results as raw jobs (is_raw=1) sorted by keyword_score.
    """
    import importlib
    from match_engine.relevance_engine import keyword_score as _kw_score

    all_jobs = []

    for site_key in sites:
        s = get_session(sid)
        if s and s.get("cancel"):
            log(f"[SCRAPE] Cancelled by user", sid)
            update_session(sid, status="done")
            return

        module_name, func_name = SITE_MAP.get(site_key, (None, None))
        if not module_name:
            log(f"[SCRAPE] Unknown site: {site_key}", sid)
            continue
        try:
            log(f"[DIRECT] Running {site_key}...", sid)
            mod = importlib.import_module(f"scrapers.{module_name}")
            scraper_fn = getattr(mod, func_name)
            try:
                kwargs = {"roles": roles}
                if site_key == "adzuna":
                    kwargs["country"] = adzuna_country
                if site_key in ("indeed", "linkedin"):
                    kwargs["location"] = location or "United States"
                if site_key == "indeed":
                    kwargs["country_indeed"] = indeed_country
                jobs = scraper_fn(**kwargs)
            except TypeError:
                jobs = scraper_fn()
            log(f"[DIRECT] {site_key} returned {len(jobs)} jobs", sid)
            all_jobs.extend(jobs)
            from utils.delay import delay as _rd
            _rd(3, 6)
        except Exception as e:
            log(f"[DIRECT] {site_key} failed: {e}", sid)

    log(f"[DIRECT] Total raw jobs: {len(all_jobs)}", sid)
    update_session(sid, scraped=len(all_jobs))
    _harvest_companies(all_jobs)

    if not all_jobs:
        log(f"[DIRECT] No jobs found", sid)
        set_raw_jobs(sid, [])
        _save_elapsed(sid)
        update_session(sid, status="done")
        return

    # Sort by keyword_score descending (simple relevance signal)
    from config import KEYWORDS_INCLUDE
    for job in all_jobs:
        job["keyword_score"] = _kw_score(
            job.get("title", ""),
            job.get("description", ""),
            job.get("tags", []),
            keywords=KEYWORDS_INCLUDE or [],
        )
    all_jobs.sort(key=lambda j: j.get("keyword_score", 0), reverse=True)

    set_raw_jobs(sid, all_jobs)
    _save_elapsed(sid)
    update_session(sid, status="done")
    log(f"[DIRECT] Pipeline complete — {len(all_jobs)} raw jobs stored", sid)
```

#### Modify `run_scrape()` (~line 183)

Add `direct_mode` parameter and routing:

```python
def run_scrape(sid, sites, keywords, resume_text,
               roles=None, adzuna_country="us", location="", indeed_country="USA",
               internship_mode=False, min_relevant=5, max_passes=3,
               original_resume="", user_email="", direct_mode=False):
    # ... existing setup code (lines 147-181) ...

    try:
        if direct_mode:
            _scrape_direct(sid, sites, roles, location, adzuna_country, indeed_country,
                           internship_mode=internship_mode, user_email=user_email)
        elif internship_mode:
            _scrape_internship(sid, ...)
        else:
            _scrape_normal(sid, ...)
    except Exception as e:
        # ... existing error handling ...
```

#### Modify `_run_scrape()` (~line 68)

Pass `direct_mode` through:

```python
def _run_scrape(req: ScrapeRequest):
    run_scrape(req.search_id, req.sites, req.keywords, req.resume_text, req.roles,
               req.adzuna_country, req.location, req.indeed_country,
               req.internship_mode, req.min_relevant, req.max_passes,
               original_resume=req.original_resume, user_email=req.user_email,
               direct_mode=req.direct_mode)
```

### 1d. `backend/api/routes/jobs.py`

Add `raw` query parameter:

```python
@router.get("")
async def list_jobs(search_id: str = "", min_score: int = 0,
                    site: str = "", experience_level: str = "",
                    sort: str = "relevant", raw: bool = False):
    if not search_id:
        return {"total": 0, "jobs": []}
    if raw:
        from db import get_raw_jobs
        jobs = get_raw_jobs(search_id)
    else:
        from db import get_filtered_jobs
        jobs = get_filtered_jobs(search_id, min_score, site, experience_level, sort)
    return {"total": len(jobs), "jobs": jobs}
```

### 1e. `backend/api/routes/scrape.py` — Update status endpoint

Add raw job count to status response for Tab 1 polling:

```python
@router.get("/status")
async def scrape_status(search_id: str = ""):
    # ... existing code ...
    s = get_session(search_id)
    if s is None:
        return { ... }

    is_direct = (s.get("max_passes", 0) == 0 and s.get("scraped", 0) > 0
                 and count_filtered_jobs(search_id) == 0)

    return {
        "status": s.get("status", "idle"),
        "last_scrape_raw": s.get("scraped") or 0,
        "last_scrape_relevant": count_filtered_jobs(search_id) if not is_direct else count_raw_jobs(search_id),
        # ... rest unchanged ...
    }
```

### Backend Verification

```bash
# Test direct mode scrape via curl
curl -X POST http://localhost:8000/scrape \
  -H "Content-Type: application/json" \
  -d '{"search_id":"test-direct-1","sites":["remoteok"],"roles":["Data Annotation"],"direct_mode":true,"location":"Remote"}'

# Poll status
curl "http://localhost:8000/scrape/status?search_id=test-direct-1"

# Get raw jobs
curl "http://localhost:8000/jobs?search_id=test-direct-1&raw=true"

# Verify normal scrape still works
curl -X POST http://localhost:8000/scrape \
  -H "Content-Type: application/json" \
  -d '{"search_id":"test-normal-1","sites":["remoteok"],"roles":["Data Analyst"],"resume_text":"Python, SQL, Tableau","direct_mode":false}'

curl "http://localhost:8000/jobs?search_id=test-normal-1"
```

---

## Phase 2: Frontend — Tab Bar HTML & State

### 2a. `frontend/index.html` — Add tab bar

Insert after line 255 (after `#stepProgress`, before `#results`):

```html
<!-- Tab Bar (hidden by default, shown when custom roles trigger dual tabs) -->
<div id="tabBar" class="hidden flex items-center gap-1 border-b border-slate-200 mb-4 -mt-1">
  <button id="tabCustom" onclick="switchTab('custom')"
    class="px-4 py-2.5 text-sm font-semibold border-b-2 border-indigo-600 text-slate-900 transition-colors rounded-t-lg hover:bg-slate-50">
    Custom Jobs <span id="tabCustomCount" class="ml-1.5 text-xs bg-slate-100 text-slate-600 px-2 py-0.5 rounded-full font-medium">0</span>
  </button>
  <button id="tabAI" onclick="switchTab('ai')"
    class="px-4 py-2.5 text-sm font-semibold border-b-2 border-transparent text-slate-400 hover:text-slate-600 transition-colors rounded-t-lg hover:bg-slate-50">
    AI Recommended <span id="tabAICount" class="ml-1.5 text-xs bg-slate-100 text-slate-600 px-2 py-0.5 rounded-full font-medium">0</span>
  </button>
</div>
```

### 2b. `frontend/js/search.js` — New state variables

Add after line 50 (`let _authEmail = "";`):

```javascript
// --- Dual Tab State ---
let suggestedRoles = [];
let searchMode = 'current';
let customSearchIds = [];
let aiSearchIds = [];
let customJobs = [];
let aiJobs = [];
let customPollTimers = [];
let aiPollTimer = null;
let activeTab = 'custom';
let roleSearchIdMap = {};
```

### 2c. `frontend/js/search.js` — Tab management functions

Add after the `// ===== HELPERS =====` section (~line 698):

```javascript
// ===== TAB MANAGEMENT =====
function showTabBar() {
  const bar = document.getElementById('tabBar');
  bar.classList.remove('hidden');
  document.getElementById('tabAI').classList.toggle('hidden', aiSearchIds.length === 0);
  switchTab('custom');
}

function hideTabBar() {
  document.getElementById('tabBar').classList.add('hidden');
}

function switchTab(tab) {
  activeTab = tab;
  const customBtn = document.getElementById('tabCustom');
  const aiBtn = document.getElementById('tabAI');
  if (tab === 'custom') {
    customBtn.className = 'px-4 py-2.5 text-sm font-semibold border-b-2 border-indigo-600 text-slate-900 transition-colors rounded-t-lg hover:bg-slate-50';
    aiBtn.className = 'px-4 py-2.5 text-sm font-semibold border-b-2 border-transparent text-slate-400 hover:text-slate-600 transition-colors rounded-t-lg hover:bg-slate-50';
  } else {
    customBtn.className = 'px-4 py-2.5 text-sm font-semibold border-b-2 border-transparent text-slate-400 hover:text-slate-600 transition-colors rounded-t-lg hover:bg-slate-50';
    aiBtn.className = 'px-4 py-2.5 text-sm font-semibold border-b-2 border-indigo-600 text-slate-900 transition-colors rounded-t-lg hover:bg-slate-50';
  }
  renderActiveTab();
}

function updateTabCounts() {
  document.getElementById('tabCustomCount').textContent = customJobs.length;
  document.getElementById('tabAICount').textContent = aiJobs.length;
}

function renderActiveTab() {
  if (activeTab === 'custom') {
    renderCustomJobs(customJobs);
  } else {
    renderJobs(aiJobs);
  }
  renderSubFilters();
  updateCountBadge(activeTab === 'custom' ? customJobs.length : aiJobs.length);
}
```

### 2d. `frontend/js/search.js` — Reset on new search

Add at the top of the search button click handler (before line 1327):

```javascript
// Reset dual-tab state
customSearchIds = [];
aiSearchIds = [];
customJobs = [];
aiJobs = [];
roleSearchIdMap = {};
activeTab = 'custom';
searchMode = 'current';
if (customPollTimer) clearInterval(customPollTimer);
if (aiPollTimer) clearInterval(aiPollTimer);
customPollTimers.forEach(t => clearInterval(t));
customPollTimers = [];
hideTabBar();
```

---

## Phase 3: Frontend — Role Classification

### 3a. `frontend/js/search.js` — Capture suggested roles

Modify the keyword extraction handler (~line 966). Add storage of suggested roles:

```javascript
document.getElementById("extractBtn").addEventListener("click", async () => {
  // ... existing code ...
  try {
    const r = await fetch("/resume/keywords", { ... });
    const d = await r.json();
    renderKeywords(d.keywords);
    if (d.suggested_roles) {
      renderSuggestedRoles(d.suggested_roles);
      suggestedRoles = d.suggested_roles;  // <-- ADD THIS LINE
    }
    setStatus("Keywords successfully extracted.", "green");
  } catch (e) { setStatus("Failed to extract keywords.", "red"); }
  // ... existing finally block ...
});
```

### 3b. `frontend/js/search.js` — Classify roles at search time

Add classification logic inside the search button handler, after `getSelectedRoles()` (~line 1327):

```javascript
const allSelectedRoles = getSelectedRoles();
const aiRoleSet = new Set(suggestedRoles.map(r => r.toLowerCase()));
const customRoleList = allSelectedRoles.filter(r => !aiRoleSet.has(r.toLowerCase()));
const aiRoleList = [...suggestedRoles];
const aiSelected = allSelectedRoles.filter(r => aiRoleSet.has(r.toLowerCase()));
for (const r of aiSelected) {
  if (!aiRoleList.find(ar => ar.toLowerCase() === r.toLowerCase())) {
    aiRoleList.push(r);
  }
}
searchMode = customRoleList.length > 0 ? 'tabs' : 'current';
```

---

## Phase 4: Frontend — Multi-Scrape Dispatch

### 4a. `frontend/js/search.js` — Modified search execution

Replace the single `fetch("/scrape", ...)` block (~lines 1353-1363) with:

```javascript
try {
  if (searchMode === 'tabs') {
    // --- Tab 1: One scrape per custom role (direct_mode) ---
    for (const role of customRoleList) {
      const roleId = crypto.randomUUID();
      customSearchIds.push(roleId);
      roleSearchIdMap[role] = roleId;
      await fetch("/scrape", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sites, roles: [role], search_id: roleId,
          direct_mode: true,
          location: getLocation() || document.getElementById("locationInput").value,
          internship_mode: internshipMode,
          adzuna_country: getAdzunaCountry(),
          indeed_country: getIndeedCountry(),
          user_email: (window.getProfile() || {}).email || "",
        })
      });
    }

    // --- Tab 2: One scrape for all AI roles (normal scored) ---
    if (aiRoleList.length > 0) {
      const aiSid = crypto.randomUUID();
      aiSearchIds = [aiSid];
      await fetch("/scrape", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sites, roles: aiRoleList, search_id: aiSid,
          resume_text: resume, keywords,
          direct_mode: false,
          location: getLocation() || document.getElementById("locationInput").value,
          internship_mode: internshipMode,
          adzuna_country: getAdzunaCountry(),
          indeed_country: getIndeedCountry(),
          user_email: (window.getProfile() || {}).email || "",
        })
      });
    }

    showTabBar();
    pollCustomScrapes();
    pollAIScrape();
  } else {
    // --- Current behavior: single scrape ---
    await fetch("/scrape", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sites, keywords, resume_text: resume, roles: allSelectedRoles,
        adzuna_country: getAdzunaCountry(),
        indeed_country: getIndeedCountry(),
        location: getLocation() || document.getElementById("locationInput").value,
        internship_mode: internshipMode,
        search_id: _searchId,
        original_resume: _uploadedFilename,
        user_email: (window.getProfile() || {}).email || "",
      })
    });
    _uploadedFilename = "";
    scrapeAttempts = 0;
    pollResults();
  }
```

---

## Phase 5: Frontend — Dual Polling

### 5a. `frontend/js/search.js` — `pollCustomScrapes()`

Add after `pollResults()` (~line 1458):

```javascript
// ===== POLL CUSTOM SCRAPES (Tab 1) =====
function pollCustomScrapes() {
  if (customPollTimer) clearInterval(customPollTimer);
  let attempts = 0;
  customPollTimer = setInterval(async () => {
    attempts++;
    let allDone = true;

    for (const sid of customSearchIds) {
      try {
        const r = await fetch(`/scrape/status?search_id=${sid}`);
        const d = await r.json();
        if (d.status === 'running') allDone = false;
      } catch {}
    }

    // Fetch raw jobs from all custom search IDs
    let allRaw = [];
    for (const sid of customSearchIds) {
      try {
        const r = await fetch(`/jobs?search_id=${sid}&raw=true`);
        const d = await r.json();
        allRaw.push(...(d.jobs || []));
      } catch {}
    }

    // Deduplicate by URL
    const seen = new Set();
    customJobs = allRaw.filter(j => {
      const key = j.url || `${j.title}|${j.company}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });

    updateTabCounts();
    if (activeTab === 'custom') renderActiveTab();

    // Update status
    if (!allDone) {
      setStatus(`Collecting custom results... ${customJobs.length} jobs found`, "blue");
      document.title = `(${customJobs.length}) Custom Jobs - AI Job Agent`;
    }

    if (allDone) {
      clearInterval(customPollTimer);
      customPollTimer = null;
      logEvent("custom_scrape_done", { roles: Object.keys(roleSearchIdMap), jobs: customJobs.length });
    }

    if (attempts > 80) {
      clearInterval(customPollTimer);
      customPollTimer = null;
    }
  }, 3000);
}
```

### 5b. `frontend/js/search.js` — `pollAIScrape()`

Add after `pollCustomScrapes()`:

```javascript
// ===== POLL AI SCRAPE (Tab 2) =====
function pollAIScrape() {
  if (aiPollTimer) clearInterval(aiPollTimer);
  const sid = aiSearchIds[0];
  if (!sid) return;
  let attempts = 0;

  aiPollTimer = setInterval(async () => {
    attempts++;
    try {
      const r = await fetch(`/scrape/status?search_id=${sid}`);
      const d = await r.json();

      if (d.status === 'running') {
        if (d.last_scrape_relevant > 0) {
          // Fetch incremental scored jobs
          const jr = await fetch(`/jobs?search_id=${sid}`);
          const jd = await jr.json();
          aiJobs = jd.jobs || [];
          updateTabCounts();
          if (activeTab === 'ai') renderActiveTab();
          setStatus(`AI scoring in progress... ${aiJobs.length} matches`, "blue");
        }
      }

      if (d.status === 'done' || d.status === 'error') {
        clearInterval(aiPollTimer);
        aiPollTimer = null;
        if (d.status === 'done') {
          const jr = await fetch(`/jobs?search_id=${sid}`);
          const jd = await jr.json();
          aiJobs = jd.jobs || [];
          updateTabCounts();
          if (activeTab === 'ai') renderActiveTab();
        }
      }
    } catch {
      clearInterval(aiPollTimer);
      aiPollTimer = null;
    }

    if (attempts > 80) {
      clearInterval(aiPollTimer);
      aiPollTimer = null;
    }
  }, 3000);
}
```

---

## Phase 6: Frontend — Raw Job Card Rendering

### 6a. `frontend/js/search.js` — `renderCustomJobs()`

Add after `renderJobs()` (~line 1672):

```javascript
// ===== RENDER CUSTOM JOBS (Tab 1 — no AI scores) =====
function renderCustomJobs(jobs) {
  const c = document.getElementById("results");
  if (!jobs.length) {
    c.innerHTML = `
      <div class="premium-card min-h-[400px] flex flex-col items-center justify-center text-center p-8">
        <div class="w-12 h-12 rounded-xl bg-slate-50 flex items-center justify-center mb-4 border border-slate-100">
          <svg class="w-5 h-5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/></svg>
        </div>
        <h3 class="text-sm font-semibold text-slate-800">No custom jobs found</h3>
        <p class="text-xs text-slate-500 mt-1">Try different roles or broaden your job board selection.</p>
      </div>`;
    return;
  }

  const showAll = voteCount >= voteThreshold || !!window.getProfile();
  const limit = 5;

  function rawCardHtml(j) {
    const siteName = siteFromUrl(j.url);
    const isSaved = j._saved || false;

    const expBadge = j.experience_level === "internship"
      ? '<span class="text-xs bg-teal-50 text-teal-700 border border-teal-100 px-2.5 py-1 rounded-md font-medium flex items-center gap-1"><svg class="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 20 20"><path d="M10.394 2.08a1 1 0 00-.788 0l-7 3a1 1 0 000 1.84L5.25 8.051a.999.999 0 01.356-.257l4-1.714a1 1 0 11.788 1.838L7.667 9.088l1.94.831a1 1 0 00.787 0l7-3a1 1 0 000-1.838l-7-3zM3.31 9.397L5 10.12v4.102a8.969 8.969 0 00-1.05-.174 1 1 0 01-.89-.89 11.115 11.115 0 01.25-3.762zM9.3 16.573A9.026 9.026 0 007 14.935v-3.957l1.818.78a3 3 0 002.364 0l5.508-2.361a11.026 11.026 0 01.25 3.762 1 1 0 01-.89.89 8.968 8.968 0 00-5.35 2.524 1 1 0 01-1.4 0z"/></svg> Internship</span>'
      : j.experience_level === "entry_level"
        ? '<span class="text-xs bg-slate-100 text-slate-700 border border-slate-200 px-2.5 py-1 rounded-md font-medium">Entry Level</span>'
        : "";

    const levelBadge = j.job_level && j.job_level !== "Not Applicable"
      ? `<span class="text-xs bg-blue-50 text-blue-700 border border-blue-100 px-2 py-0.5 rounded-md font-medium">${j.job_level}</span>`
      : "";

    const companyHtml = j.company_url
      ? `<span class="font-medium text-indigo-600 hover:underline cursor-pointer" onclick="event.preventDefault(); event.stopPropagation(); window.open('${j.company_url.replace(/'/g, "\\'")}', '_blank')">${j.company}</span>`
      : `<span class="font-medium">${j.company}</span>`;

    const tagsHtml = j.tags && j.tags.length
      ? `<div class="mt-3 flex flex-wrap gap-1.5">${j.tags.slice(0, 6).map(t =>
          `<span class="text-xs bg-slate-100 text-slate-600 px-2 py-0.5 rounded-md">${typeof t === 'string' ? t : ''}</span>`
        ).join("")}</div>`
      : "";

    return `
    <a href="${j.url}" target="_blank" class="block group relative bg-white rounded-2xl p-5 sm:p-6 border border-[#e8ecf1] hover:border-slate-300 hover:shadow-lg transition-all duration-300 outline-none focus:ring-2 focus:ring-indigo-500">
      <div class="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
        <div class="flex-1 min-w-0">
          <div class="flex flex-wrap items-center gap-2 mb-2">
            <h3 class="text-sm sm:text-base font-semibold text-slate-900 group-hover:text-indigo-600 transition-colors truncate pr-1">${j.title}</h3>
            ${expBadge} ${levelBadge}
          </div>
          <p class="text-sm text-slate-600 flex items-center gap-2 truncate">
            ${companyHtml}
            <span class="w-1 h-1 rounded-full bg-slate-300 shrink-0"></span>
            <span>${j.location}</span>
            ${j.salary ? `<span class="w-1 h-1 rounded-full bg-slate-300 shrink-0"></span><span class="premium-badge bg-emerald-50 text-emerald-700 border-emerald-100 font-medium">${j.salary}</span>` : ""}
            ${j.date_posted ? `<span class="w-1 h-1 rounded-full bg-slate-300 shrink-0"></span><span class="text-xs text-slate-400">${relativeDate(j.date_posted)}</span>` : ""}
          </p>
        </div>
      </div>

      ${tagsHtml}

      <div class="flex items-center justify-between mt-4 pt-4 border-t border-slate-100">
        <div class="flex items-center gap-2.5 flex-1 pr-3 min-w-0">
          <button class="bookmark-btn shrink-0 text-xs font-semibold transition-all duration-200 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border ${isSaved ? 'bg-indigo-500 text-white border-indigo-500 hover:bg-indigo-600' : 'bg-indigo-50 text-indigo-600 border-indigo-200 hover:bg-indigo-100 active:bg-indigo-200'}" data-url="${j.url || ''}" onclick="toggleSaveJob(event)" title="Save job">
            ${isSaved
              ? '<svg class="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/></svg> Saved'
              : '<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4"/></svg> Save'
            }
          </button>
          <button class="shrink-0 text-xs font-semibold transition-all duration-200 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border bg-violet-50 text-violet-600 border-violet-200 hover:bg-violet-100 active:bg-violet-200 referral-btn" data-company="${j.company.replace(/"/g, '&quot;')}" onclick="event.preventDefault(); event.stopPropagation(); window._referralJobTitle='${(j.title||'').replace(/'/g, "\\'")}'; window._referralMatchScore=0; window._referralJobUrl='${(j.url||'').replace(/'/g, "\\'")}'; showReferralUsers('${j.company.replace(/'/g, "\\'")}')" title="See referrals at this company">
            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z"/></svg>
            <span class="referral-label">Referrals</span>
          </button>
        </div>
        <div class="flex items-center gap-1.5 text-xs font-medium text-slate-400 shrink-0">
          <span>via ${siteName}</span>
          <svg class="w-4 h-4 group-hover:text-indigo-600 group-hover:translate-x-0.5 transition-all" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14 5l7 7m0 0l-7 7m7-7H3"></path></svg>
        </div>
      </div>
    </a>`;
  }

  if (jobs.length > limit && !showAll) {
    const lockedCount = jobs.length - limit;
    const profile = window.getProfile();
    const unlockHtml = profile
      ? `<button class="premium-btn premium-btn-primary mt-3" onclick="handleVote(this)">Unlock All Results <span class="bg-white/20 px-1.5 rounded text-xs">${voteCount}/${voteThreshold}</span></button>`
      : `<button class="premium-btn premium-btn-primary mt-3" onclick="showAuthModal()">Sign in</button>`;
    c.innerHTML = jobs.slice(0, limit).map(rawCardHtml).join("") + `
      <div class="relative rounded-2xl overflow-hidden mt-4">
        <div class="blur-job space-y-4 px-1">${jobs.slice(limit, limit+2).map(rawCardHtml).join("")}</div>
        <div class="absolute inset-0 flex items-center justify-center bg-gradient-to-t from-[#f8fafc] via-white/80 to-transparent">
          <div class="bg-white border border-[#e8ecf1] rounded-2xl p-6 text-center shadow-lg mx-4 max-w-sm w-full transform -translate-y-4">
            <div class="w-12 h-12 rounded-2xl bg-slate-50 border border-slate-100 flex items-center justify-center mx-auto mb-3">
              <svg class="w-5 h-5 text-slate-700" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"></path></svg>
            </div>
            <h4 class="font-semibold text-slate-900 text-sm">${lockedCount} more custom jobs hidden</h4>
            <p class="text-xs text-slate-500 mt-1">${profile ? 'Support the project to unlock all custom results.' : 'Sign in to unlock all results and save jobs.'}</p>
            ${unlockHtml}
          </div>
        </div>
      </div>`;
  } else {
    c.innerHTML = jobs.map(rawCardHtml).join("");
  }

  // Load referral counts for custom tab
  const profile = window.getProfile();
  if (profile) {
    const companies = [...new Set(jobs.map(j => j.company).filter(Boolean))];
    if (companies.length) {
      fetch(`/api/users/company-counts?companies=${encodeURIComponent(companies.join(","))}`)
        .then(r => r.json())
        .then(d => {
          const counts = d.counts || {};
          document.querySelectorAll(".referral-btn[data-company]").forEach(btn => {
            const company = btn.getAttribute("data-company");
            const count = counts[company] || 0;
            const label = btn.querySelector(".referral-label");
            if (label) label.textContent = `Referrals - ${count}`;
          });
        }).catch(() => {});
    }
  }
}
```

### 6b. `frontend/js/search.js` — Sub-filters for custom tab

Add after `renderCustomJobs()`:

```javascript
// ===== SUB-FILTERS (role filters within Custom tab) =====
function renderSubFilters() {
  const bar = document.getElementById("filterBar");
  if (searchMode !== 'tabs' || activeTab !== 'custom' || Object.keys(roleSearchIdMap).length <= 1) {
    // Use standard filter bar for single-role or AI tab
    if (activeTab !== 'custom' || searchMode !== 'tabs') {
      renderFilterBar();
    } else {
      bar.classList.add("hidden");
    }
    return;
  }

  bar.classList.remove("hidden");
  const roles = Object.keys(roleSearchIdMap);
  let html = `<span class="cursor-pointer px-3 py-1.5 rounded-lg border text-sm font-medium transition-colors bg-slate-800 text-white border-slate-800" data-role-filter="all">All Custom (${customJobs.length})</span>`;

  for (const role of roles) {
    const sid = roleSearchIdMap[role];
    const count = customJobs.filter(j => j._searchId === sid).length;
    html += `<span class="cursor-pointer px-3 py-1.5 rounded-lg border text-sm font-medium transition-colors bg-white text-slate-600 border-slate-200 hover:bg-slate-50" data-role-filter="${role}">${role} (${count})</span>`;
  }

  bar.innerHTML = html;
  bar.querySelectorAll("[data-role-filter]").forEach(el => {
    el.addEventListener("click", () => {
      const role = el.dataset.roleFilter;
      if (role === "all") {
        renderCustomJobs(customJobs);
      } else {
        const sid = roleSearchIdMap[role];
        renderCustomJobs(customJobs.filter(j => j._searchId === sid));
      }
      // Update active state
      bar.querySelectorAll("[data-role-filter]").forEach(b => {
        b.classList.toggle("bg-slate-800", b.dataset.roleFilter === role);
        b.classList.toggle("text-white", b.dataset.roleFilter === role);
        b.classList.toggle("border-slate-800", b.dataset.roleFilter === role);
        b.classList.toggle("bg-white", b.dataset.roleFilter !== role);
        b.classList.toggle("text-slate-600", b.dataset.roleFilter !== role);
        b.classList.toggle("border-slate-200", b.dataset.roleFilter !== role);
      });
    });
  });
}
```

**Note:** To support sub-filter counting, raw jobs need a `_searchId` tag. Add this during aggregation in `pollCustomScrapes()`:

```javascript
// Inside pollCustomScrapes, when aggregating:
for (const sid of customSearchIds) {
  try {
    const r = await fetch(`/jobs?search_id=${sid}&raw=true`);
    const d = await r.json();
    (d.jobs || []).forEach(j => { j._searchId = sid; });
    allRaw.push(...(d.jobs || []));
  } catch {}
}
```

---

## Phase 7: Frontend — Integration Points

### 7a. Modify `applyThreshold()` (~line 942)

```javascript
function applyThreshold() {
  if (searchMode === 'tabs') {
    renderActiveTab();
  } else {
    const displayJobs = getFilteredJobs();
    const companies = displayJobs.map(j => j.company);
    if (typeof window.loadCompanyUserCounts === "function") {
      window.loadCompanyUserCounts(companies).then(() => {
        renderJobs(displayJobs);
      });
    } else {
      renderJobs(displayJobs);
    }
    updateCountBadge(displayJobs.length);
    renderFilterBar();
  }
}
```

### 7b. Modify `checkSavedStatuses()`

The saved status check should work on the active tab's jobs. Since `customJobs` and `aiJobs` are separate arrays, update the batch check to use the correct set:

```javascript
async function checkSavedStatuses() {
  const profile = window.getProfile();
  if (!profile) return;
  const jobsToCheck = searchMode === 'tabs'
    ? (activeTab === 'custom' ? customJobs : aiJobs)
    : allJobs;
  // ... existing batch check logic using jobsToCheck ...
}
```

### 7c. Modify cache restore (~line 1674)

```javascript
(async function restoreLastSearch() {
  const raw = localStorage.getItem(SEARCH_CACHE_KEY);
  if (!raw) return;
  let saved;
  try { saved = JSON.parse(raw); } catch { return; }
  if (!saved || Date.now() - saved.timestamp > SEARCH_CACHE_TTL) return;

  try {
    if (saved.searchMode === 'tabs') {
      // Restore dual-tab search
      searchMode = 'tabs';
      customSearchIds = saved.customSearchIds || [];
      aiSearchIds = saved.aiSearchIds || [];
      roleSearchIdMap = saved.roleSearchIdMap || {};

      // Check if all scrapes are done
      let allDone = true;
      for (const sid of [...customSearchIds, ...aiSearchIds]) {
        const r = await fetch(`/scrape/status?search_id=${sid}`);
        const d = await r.json();
        if (d.status === 'running') allDone = false;
      }

      if (allDone) {
        // Fetch all results
        for (const sid of customSearchIds) {
          const r = await fetch(`/jobs?search_id=${sid}&raw=true`);
          const d = await r.json();
          (d.jobs || []).forEach(j => { j._searchId = sid; });
          customJobs.push(...(d.jobs || []));
        }
        const seen = new Set();
        customJobs = customJobs.filter(j => {
          const key = j.url || `${j.title}|${j.company}`;
          if (seen.has(key)) return false;
          seen.add(key);
          return true;
        });

        if (aiSearchIds.length) {
          const r = await fetch(`/jobs?search_id=${aiSearchIds[0]}`);
          const d = await r.json();
          aiJobs = d.jobs || [];
        }

        showTabBar();
        updateTabCounts();
        renderActiveTab();
      } else {
        showTabBar();
        pollCustomScrapes();
        pollAIScrape();
      }
    } else {
      // Current restore logic unchanged
      _searchId = saved.searchId;
      _searchComplete = true;
      const r = await fetch(`/scrape/status?search_id=${saved.searchId}`);
      const status = await r.json();
      if (status.status === "done" || status.status === "error") {
        if (status.status === "done") await loadResults(status);
      }
    }
  } catch {}
})();
```

Update the cache storage in `loadResults()` and at end of tab-mode search:

```javascript
// After search completes in tabs mode, cache:
localStorage.setItem(SEARCH_CACHE_KEY, JSON.stringify({
  searchMode,
  customSearchIds,
  aiSearchIds,
  roleSearchIdMap,
  timestamp: Date.now(),
  params: { sites, roles: [...customRoleList, ...aiRoleList], location, internshipMode },
}));
```

### 7d. Modify cancel search

Update the existing stop handler to cancel all search IDs:

```javascript
// Replace existing cancel logic with:
async function cancelAllScrapes() {
  const allIds = [...customSearchIds, ...aiSearchIds];
  if (allIds.length === 0 && _searchId) allIds.push(_searchId);
  for (const sid of allIds) {
    fetch(`/scrape/stop?search_id=${sid}`, { method: "POST" }).catch(() => {});
  }
  if (customPollTimer) clearInterval(customPollTimer);
  if (aiPollTimer) clearInterval(aiPollTimer);
  if (pollTimer) clearInterval(pollTimer);
  hideTabBar();
}
```

### 7e. Window exports

Add new functions to `window` (~line 1724):

```javascript
window.switchTab = switchTab;
```

---

## Phase 8: Edge Cases & Polish

### 8a. Role similarity check (near-duplicates)

Add a helper function to detect if a custom role overlaps with an AI-suggested role:

```javascript
function isRoleSimilar(roleA, roleB) {
  const a = roleA.toLowerCase().replace(/[^a-z0-9 ]/g, '').trim();
  const b = roleB.toLowerCase().replace(/[^a-z0-9 ]/g, '').trim();
  if (a === b) return true;
  if (a.includes(b) || b.includes(a)) return true;
  // Simple word overlap check
  const wordsA = a.split(/\s+/);
  const wordsB = b.split(/\s+/);
  const common = wordsA.filter(w => wordsB.includes(w) && w.length > 3);
  return common.length >= Math.min(wordsA.length, wordsB.length) * 0.6;
}
```

Use during role classification to merge overlapping roles into Tab 2:

```javascript
// After classifying roles, check for overlaps:
const mergedCustomRoles = customRoleList.filter(cr =>
  !aiRoleList.some(ai => isRoleSimilar(cr, ai))
);
const overlappingRoles = customRoleList.filter(cr =>
  aiRoleList.some(ai => isRoleSimilar(cr, ai))
);
// Overlapping roles go to Tab 2 (AI scored)
for (const r of overlappingRoles) {
  if (!aiRoleList.find(ar => ar.toLowerCase() === r.toLowerCase())) {
    aiRoleList.push(r);
  }
}
customRoleList = mergedCustomRoles;

// If all custom roles overlapped, fall back to no-tabs mode
if (customRoleList.length === 0) {
  searchMode = 'current';
}
```

### 8b. Empty states

| Scenario | Display |
|----------|---------|
| Custom tab has 0 jobs | "No custom jobs found. Try different roles or broaden your job boards." |
| AI tab has 0 jobs | "No AI-scored matches yet. Try uploading your resume for personalized results." |
| Both tabs empty | Single empty state: "No jobs found for your search." |

### 8c. Single sub-filter (1 custom role)

When only 1 custom role is selected, hide the sub-filter bar (no need to filter by role when there's only one). The standard site/experience filter bar applies instead.

---

## File Change Summary

| File | Type | Changes | Lines Changed (est.) |
|------|------|---------|---------------------|
| `backend/api/schemas.py` | Modify | Add `direct_mode` field | +1 |
| `backend/db.py` | Modify | Add `set_raw_jobs()`, `get_raw_jobs()`, `count_raw_jobs()` | +60 |
| `backend/api/routes/scrape.py` | Modify | Add `_scrape_direct()`, route `direct_mode` in `run_scrape()` | +60 |
| `backend/api/routes/jobs.py` | Modify | Add `raw` query param | +8 |
| `frontend/index.html` | Modify | Add tab bar HTML | +12 |
| `frontend/js/search.js` | Modify | Role classification, multi-scrape, dual polling, `renderCustomJobs()`, sub-filters, cache, cancel, reset | +350 |

**No new files created.** All changes are modifications to existing files.

---

## Implementation Order

| Phase | What | Testable? |
|-------|------|-----------|
| 1 | Backend direct scrape mode | curl tests |
| 2 | Frontend tab bar HTML + state | Visual tab bar (non-functional) |
| 3 | Frontend role classification | Console logging of classified roles |
| 4 | Frontend multi-scrape dispatch | Fire parallel scrapes, verify via curl |
| 5 | Frontend dual polling | Tabs populate with results |
| 6 | Frontend raw card rendering | Tab 1 shows clean cards without scores |
| 7 | Frontend integration points | Cache restore, cancel, saved status |
| 8 | Edge cases & polish | Role similarity, empty states, sub-filters |

---

## Verification Checklist

- [ ] Custom-only search → two tabs appear
- [ ] AI-only search → no tabs, current behavior
- [ ] Mixed search (custom + AI) → two tabs
- [ ] Tab 1 shows raw cards (no score badge, no AI note, no progress bar)
- [ ] Tab 2 shows scored cards (full current behavior)
- [ ] Tab switching works correctly
- [ ] Sub-filters within Tab 1 filter by role
- [ ] Save/unsave works on both tabs
- [ ] Referral buttons work on both tabs
- [ ] Gated results (vote/sign-in wall) work per-tab
- [ ] Cache restore works for tab-mode searches
- [ ] Cancel stops all scrapes
- [ ] New search resets all tab state
- [ ] Internship mode works with direct scrapes
- [ ] Partial scrape failure doesn't break other tabs
- [ ] Role similarity detection merges overlapping roles

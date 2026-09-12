# Plan: Careers tab — jobs from company career pages

## Goal
Pull open roles directly from company career pages (not just job boards) and surface them on a dedicated **Careers page/tab**. Adopts monitor patterns from [colophon-group/jobseek](https://github.com/colophon-group/jobseek) (MIT — license-clean; we do **not** reuse their CC BY-NC job data or self-host their stack).

## Decisions (2026-09-12)
- Companies are **admin-managed** (admin page); ATS/monitor type is auto-detected per company.
- Sources: **ATS public APIs + sitemaps + JSON-LD** (jobseek-style monitors), no fragile HTML scraping/Playwright.
- Jobs surface on a **separate Careers page/tab** (not merged into the board search cache).
- Refresh: **daily scheduled pull** (scheduler.py, apscheduler) + manual admin refresh with last-run status.

## Change list

### Backend
1. **Tables** (`backend/db.py` migrations):
   - `career_sources` — id, company, domain, careers_url, monitor, monitor_config, detect_status, last_pulled_at, last_error, pull_count, active.
   - `career_jobs` — id, company, monitor, title, location, url UNIQUE, remote, posted_at, description, active, first_seen, last_seen.
   - Canonicalize/dedupe by source URL; rows not seen again marked inactive (jobseek "source-URL identity" model).

2. **Monitor registry** — `backend/scrapers/careers_scraper.py` (mirror the `SITE_MAP` scraper pattern, `scrape.py:88`):
   - **ATS monitors** (public JSON, no auth):
     - Greenhouse `https://boards-api.greenhouse.io/v1/boards/{token}/jobs`
     - Lever `https://api.lever.co/v0/postings/{slug}?mode=json`
     - Ashby `https://api.ashbyhq.com/posting-api/job-board/{org}`
     - SmartRecruiters `https://api.smartrecruiters.com/v1/companies/{alias}/postings` (paginated)
     - Workable `https://apply.workable.com/api/v1/widget/accounts/{sub}`
   - **Sitemap monitor** — fetch `sitemap.xml` (via `robots.txt` Sitemap: line or common paths), filter job-looking `<loc>` URLs.
   - **JSON-LD monitor** — fetch each discovered posting URL, parse `script[type="application/ld+json"]` `JobPosting` (bs4 + `json`) → title, company, `jobLocation`, `datePosted`, `employmentType`, apply URL.
   - All normalize to one job-dict shape → upsert `career_jobs`.

3. **Auto-detect util** — given company domain/careers URL, classify monitor: ATS markers (greenhouse/lever.co/ashby/smartrecruiters/workable/bamboohr) → sitemap present → JSON-LD crawl → `unsupported`; store detect_status.

4. **API routes** — `backend/api/routes/careers.py`:
   - Public: `GET /api/careers/jobs?company=&q=&remote=&limit=` (newest-first), `GET /api/careers/sources` (filter list).
   - Admin (`_check_admin`, `admin.py:348`): sources CRUD, `POST /api/careers/detect`, `POST /api/careers/refresh`, per-source last-run status.
   - Register router + `/careers` page in `backend/api/main.py`; add `/careers` to auth-guard `_PUBLIC_PATHS`.

5. **Scheduler** — daily careers pull job in `backend/scheduler.py` (apscheduler, concurrency cap like prewarm).

### Frontend
6. **`frontend/careers.html`** + **`frontend/js/careers.js`** (new) — public page: company dropdown (from `/api/careers/sources`), title search, remote toggle, newest-first job cards (title/company/location/apply link, monitor badge). Reuse Tailwind + shared js (`api.js`, `utils.js`).
7. **Entry point** — "Careers" link in app header (`index.html`) and landing nav (`landing.html`).

### Admin
8. **Careers tab** in `frontend/admin.html` / `js/admin.js`: add company + domain, **Detect** button (auto-detect monitor), list sources with status/last pull, **Refresh All**, per-source error display.

## Tests & verification
9. `backend/tests/test_integration.py` (`TestCareers`, mirroring `TestAdminBackup` style):
   - detect logic (fixture HTML for each ATS marker / sitemap / generic).
   - each monitor parse → normalized rows (mocked `requests`).
   - dedupe by URL + inactivity marking.
   - public endpoints 200; admin endpoints 403 non-admin / 200 admin.
   - scheduler task smoke.
10. Full suite (currently 90 → ~96), `py_compile`, `node --check` on touched JS.
11. Manual: add company → detect → refresh → jobs appear on `/careers`; re-run marks removed postings inactive.

## Deploy
- Only commit/push/deploy when the user explicitly asks.

## Relevant files
- `backend/api/routes/scrape.py` — `SITE_MAP:88` scraper registration pattern
- `backend/scheduler.py` — apscheduler tasks
- `backend/db.py` — migration block pattern (`users` ALTERs at `:340-373`)
- `backend/api/routes/admin.py` — `_check_admin:348` for admin-gated careers routes
- `backend/api/main.py` — router mounting + page redirects `:268-293` + public path list
- `frontend/index.html`, `frontend/landing.html` — nav links
- `github.com/colophon-group/jobseek` — reference monitor patterns (MIT); ports only, no data reuse
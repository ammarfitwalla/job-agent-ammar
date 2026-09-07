# Load / Capacity Test Plan — job-agent (jobawn.com)

Date: 2026-09-07
Status: PLAN ONLY — nothing has been run yet.

## Objective
Determine the server's capacity for concurrent users and sustained request throughput, and identify where it bottlenecks, so we know safe operating limits for production.

## Confirmed runtime facts (from code)

| Fact | Evidence |
|---|---|
| Single uvicorn worker (1 process) | `backend/Dockerfile:44` — `uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}` |
| All DB writes serialized by one process-wide lock | `backend/db.py:12` `_write_lock = threading.Lock()` |
| SQLite reads concurrent (WAL), writes still single-writer | `backend/db.py:21-22` — `PRAGMA journal_mode=WAL`, `busy_timeout=5000` |
| Every write opens a fresh connection + commit | `_get_conn()` per call; e.g. `add_event`, `log_visit_start` |
| Rate limiter is in-memory, per (route, IP), no off-switch | `backend/utils/rate_limiter.py`; no env toggle |
| Client IP = first `X-Forwarded-For` entry (spoofable in test) | `backend/utils/client_ip.py`; nginx appends via `proxy_add_x_forwarded_for` |
| Cheap endpoints | `/`, `/app`, `/admin` FileResponse; `/health`; static mount `frontend/` (`backend/api/main.py:147-180`) |
| Write-heavy endpoints (the capacity gate) | `POST /api/events` (120/min/IP), `POST /api/visit/start|ping|end` (120/min/IP) |
| Heavy LLM paths (Groq-quota-bound, NOT server-bound) | `POST /scrape` (6/min/IP), resume/keywords, jobs/check-relevance, referrals/score |

## Concurrency model (why things behave the way they will)
- SQLite WAL gives concurrent READS.
- All WRITES serialize on `_write_lock` inside the single process → requests queue on the lock.
- Result: sustained write-RPS plateaus near `1 / (avg write latency)`; latency grows ~linearly with concurrency beyond that.
- => Server capacity ≈ write throughput ceiling, NOT CPU. Reads/static are essentially free until threads exhaust (FastAPI default threadpool ≈ 40).
- "Concurrent search users" is additionally gated by the 6 scrapes/min/IP rule and Groq quota.

## Planned test approach (agreed)
- k6 from the local Windows machine against `https://jobawn.com` (real network: WAN + TLS + nginx).
- Each VU sends a unique `X-Forwarded-For` + `session_id` to bypass per-IP rate limits and measure raw server capacity.
- Run during low-traffic window only.
- Do NOT hammer `/scrape` with careless volume (LLM cost). Scrape gets a tiny, cost-aware probe.

## Install (once, on the Windows box)
```
winget install k6
```

## Phase 1 — Baseline (single user noise floor)
`k6 run baseline.js`  (30s, 1 VU: GET /, /app, /health, one JS asset)
Expected: p95 well under 200ms; establishes TLS/nginx overhead.

## Phase 2 — Write ceiling (the capacity number)
- **2a. Microbenchmark (optional, no network, cheap):** inside container, time 1000 sequential `add_event` writes → predicted write-RPS.
- **2b. k6 ramp on `POST /api/events`:** stages 10 → 25 → 50 → 100 → 200 VU, 60s each.
  - Record: RPS reached, p95/p99 latency, error %.
  - Knee = p95 > ~800ms or any 500 / `database is locked`.

## Phase 3 — Realistic session mix ("concurrent users")
One VU = one user session: GET /app → 3x POST /api/events → POST /api/visit/start → POST /api/visit/end.
Ramp until p95 ≥ ~1s or error > 1%. Convert:
  `concurrent users ≈ sustained write-RPS / (beacons per session)`

## Phase 4 — Scrape/search probe (cost-aware, tiny)
1 → 2 → 4 concurrent `POST /scrape` (unique XFF), fixed small resume/roles. Measure per-scrape p95 duration + Groq usage. Do not treat as stress — it's a latency/quota probe.

## JSON shapes the scripts will use
`POST /api/events`
```json
{ "session_id": "", "event": "k6_test", "data": {}, "elapsed": 0 }
```
`POST /api/visit/start`
```json
{ "visit_id": "", "device_type": "desktop", "path": "/app", "referer": "", "session_id": "", "user_email": "" }
```
`POST /api/visit/end`
```json
{ "visit_id": "", "total_duration": 10 }
```
`POST /scrape` (probe only)
```json
{ "search_id": "", "sites": ["indeed"], "keywords": [], "roles": ["Software Engineer"], "location": "Texas", "city": "", "state": "TX", "country": "USA", "resume_text": "<short fixed resume>", "scrape_limit": 5, "hours_old": 168 }
```

## k6 script skeleton (to be finalized at run time)
```js
// events-ramp.js — core capacity probe
import http from "k6/http";
import { check } from "k6";

export const options = {
  scenarios: {
    ramp: {
      executor: "ramping-vus",
      startVUs: 0,
      stages: [
        { duration: "15s", target: 10 },
        { duration: "60s", target: 10 },
        { duration: "15s", target: 25 },
        { duration: "60s", target: 25 },
        { duration: "15s", target: 50 },
        { duration: "60s", target: 50 },
        { duration: "15s", target: 100 },
        { duration: "60s", target: 100 },
        { duration: "15s", target: 200 },
        { duration: "60s", target: 200 },
      ],
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.05"],
    http_req_duration: ["p(95)<1500"],
  },
};

const BASE = "https://jobawn.com";

export default function () {
  const ip = `10.${__VU % 250}.${__ITER % 250}.${(__VU + __ITER) % 255}`;
  const headers = {
    "Content-Type": "application/json",
    "X-Forwarded-For": ip,
  };
  const sid = `loadtest-${__VU}-${__ITER}`;
  const payload = JSON.stringify({ session_id: sid, event: "k6_test", data: {}, elapsed: 0 });
  const res = http.post(`${BASE}/api/events`, payload, { headers });
  check(res, { "2xx": (r) => r.status >= 200 && r.status < 300 });
}
```
Session-mix and scrape-probe scripts follow the same pattern (mix GET /app + 3 events + visit start/end; or scrape probe with unique search_id/session).

## What to capture while tests run (server side, second terminal)
- `docker stats`  → job-agent + nginx CPU/MEM (confirms CPU vs lock-bound)
- `docker logs --tail 200 --since 600s job-agent` → uvicorn access lines, errors, 5xx
- Error codes returned to k6 (429 = XFF not honored; 500/503 = real server distress)

## Cleanup after tests
Delete test rows from production DB (inside container, python):
```python
from db import _get_conn
with _get_conn() as (c, cur):
    cur.execute("DELETE FROM events WHERE session_id LIKE 'loadtest-%'")
    cur.execute("DELETE FROM visits WHERE visit_id LIKE 'loadtest-%'")
    c.commit()
```
(Only needed for write probe phases; baseline/static phases touch nothing.)

## Guardrails / decisions already made
- Test directly against prod via nginx (real-world path) — approved.
- k6 chosen — approved.
- XFF spoofing accepted to measure raw capacity; real per-IP limits still apply in production.
- Scrape edge only probed 1–4 concurrent, small result sets, to avoid LLM cost.

## Open items / follow-ups
- If nginx strips or normalizes XFF, we'll see 429s → fall back to measuring with imposed limits (that itself is a useful "real users" number).
- If bottleneck is clearly the single-writer lock, likely follow-up is batching event writes (queue + flush) or WAL checkpoint tuning — NOT this test's scope.
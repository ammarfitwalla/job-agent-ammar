# Extend Visit Tracking to Landing & Profile Pages

## Context / Problem

Visit tracking (`POST /api/visit/start` / `/end`) currently fires **only on `/app`**.
The frontend code lives in a self-contained IIFE inside `frontend/js/search.js` (lines
145-185), which is loaded **only** by `frontend/index.html` (route `/app`).

As a result:
- `/` (landing page), `/profile`, `/referrals`, `/admin` generate **zero** `visits` rows.
- The stored `path` is always `"/app"` (raw `window.location.pathname`, no client-side
  routing), so the admin "Page" column shows `/app` for every row.
- `user_email` is always sent as `""`, even though the visits table and backend fully
  support storing it (`visits.user_email` in `db.py:153`, parsed in `visits.py:44`).

## Goal

Track visits on **`/` (landing)** and **`/profile`** in addition to `/app`, and populate
the logged-in `user_email` where auth context exists.

## No backend changes required

- `/api/visit/start` and `/api/visit/end` are public (rate-limited 120 req / 60 s per IP).
- The backend stores whatever `path` string is sent and already persists `user_email`.
- Admin reads the data via `GET /api/admin/visits` (unchanged).

## Frontend changes

### 1. New `frontend/js/track.js`

Plain (non-module) script — safe to load on any page. Extract the visit logic from
`search.js` and add email resolution:

```js
(function () {
  var _visitId = crypto.randomUUID();
  var _visitStart = Date.now();

  function _detectDevice() {
    var ua = navigator.userAgent;
    if (/Mobi|Android|iPhone|iPad|iPod|BlackBerry|Windows Phone|IEMobile|Opera Mini/i.test(ua)) return "phone";
    if (/Tablet|iPad|PlayBook|Silk/i.test(ua)) return "tablet";
    return "desktop";
  }

  function _visitBeacon(endpoint, data) {
    try {
      navigator.sendBeacon(endpoint, new Blob([JSON.stringify(data)], { type: "application/json" }));
    } catch (e) {}
  }

  // api.js is loaded BEFORE track.js on every page that has it. Landing has no
  // api.js, so guard the accessor.
  var _email = (window.getAuthEmail ? window.getAuthEmail() : "") || "";

  _visitBeacon("/api/visit/start", {
    visit_id: _visitId,
    device_type: _detectDevice(),
    path: window.location.pathname,
    referer: document.referrer || "",
    session_id: "",
    user_email: _email,
  });

  function _endVisit() {
    _visitBeacon("/api/visit/end", {
      visit_id: _visitId,
      total_duration: (Date.now() - _visitStart) / 1000,
    });
  }

  window.addEventListener("beforeunload", _endVisit);
  window.addEventListener("pagehide", _endVisit);
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "hidden") _endVisit();
  });
})();
```

### 2. `frontend/js/search.js`

Delete the visit-tracking IIFE (currently lines 145-185) — it moves verbatim into
`track.js`. (Search still keeps its own session-event handlers; only the visit-beacon
block is removed.)

### 3. `frontend/index.html` (route `/app`)

Insert `<script src="/js/track.js"></script>` **after** `api.js` (line 593) and directly
**before** `search.js` (line 599), so `window.getAuthEmail()` resolves at load time.
`user_email` will now be populated for `/app` too (improvement over today's blank value).

### 4. `frontend/profile.html` (route `/profile`)

Add `<script src="/js/track.js"></script>` before `</body>` (after `api.js` at line 497,
e.g. alongside `main.js` at line 504). Auth exists on this page → `user_email` populated.

### 5. `frontend/landing.html` (route `/`)

Add `<script src="/js/track.js"></script>` before `</body>` (alongside `terms.js` at line
570). No `api.js` here → guard sends blank `user_email` (anonymous visit).

### 6. Admin Visits table — show user_email (recommended)

- `frontend/admin.html:650` — add `<th>User</th>` to the Visits table header.
- `frontend/js/admin.js:483-491` — render `v.user_email` in the row; bump the empty-state
  `colspan="6"` to `colspan="7"`.

## Result

| Page | path stored | user_email |
|---|---|---|
| `/` (landing) | `/` | blank (public, no api.js) |
| `/app` (search) | `/app` | logged-in email |
| `/profile` | `/profile` | logged-in email |

Admin **DB → Sessions → Visits** subtab will show rows for all three pages with email
where applicable. No new backend work, no schema migration.

## Manual verification

- Load `/` → new visit row with `path="/"`.
- Load `/profile` while logged in → new visit row with `path="/profile"` + email.
- Load `/app` while logged in → new visit row with `path="/app"` + email (behavior change:
  previously email was blank).
- Confirm page switch still works: leaving a page fires the end beacon.

## Notes / caveats

- `enforceSessionOnLoad` (api.js) may clear a stale/expired token on `DOMContentLoaded`,
  i.e. after the start beacon already fired with a stale email. Acceptable; beacon email
  is best-effort analytics, not an auth check.
- `/api/visit/ping` heartbeat remains unused by the frontend (unchanged).
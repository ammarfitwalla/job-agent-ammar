# Plan: User location (state/country) + admin registrations columns

## Goal
Collect user location (state and country) on the profile page and surface it in the admin **sessions → registrations** tab, along with a resume link for each registered user.

## Decisions (from user Q&A)
- Reuse the **search-page location autocomplete** text box on the profile page (no free-text state/country inputs, no country dropdown).
- State/Country are **optional** on save — the form never blocks.
- Store only `state` and `country` on the user (city is ignored).

## Change list

### Location picker — reuse the search-page one
The search autocomplete lives in `frontend/js/search.js:1338-1448` (`fetchCountries` → external `api.countrystatecity.in`, `loadStates` → `/states`, `searchState` / `selectLocation` render "State, Country" dropdown). It is coupled to search-page globals, so:

1. **New `frontend/js/location-picker.js`** — shared module exporting `initLocationPicker({ inputId, resultsId, onSelect, onClear })`, encapsulating the search-page behavior:
   - `fetchCountries()` (`api.countrystatecity.in`, same key already embedded client-side in `search.js:1342`)
   - `loadStates()` → `GET /states` (`d.states`)
   - match builder (country matches + state matches, label `"State, Country"`)
   - dropdown render + select/clear, returns the picked location to `onSelect`

2. **Refactor `frontend/js/search.js`** to call `initLocationPicker` (single source of truth); keep its `#locationInput`/`#locationResults`/`#selectedLocation` DOM and `updateNaukriEligibility` hooks working identically.

3. **Profile page uses the same picker** on the edit form with the same UX; persists `state` + `country`.

### Backend
4. **`backend/db.py`**
   - Add `state TEXT DEFAULT ''`, `country TEXT DEFAULT ''` to the `users` `CREATE TABLE` (`db.py:99-111`).
   - Add the same two columns to the existing migration block (`db.py:347`, pattern of company/position/localized columns).
   - `update_user_profile` (`db.py:1148`) — accept + persist `state`, `country`.

5. **`backend/api/routes/profile.py`**
   - `UpdateProfileRequest` (`:19`) — add `state`, `country`.
   - `profile_get` (`:34`) — include `state`, `country` in the response.
   - `profile_update` (`:61`) — pass through to `update_user_profile`.

6. **New admin resume endpoint** — `GET /api/admin/users/{email}/resume` in `backend/api/routes/admin.py`:
   - `_check_admin` (existing admin guard) + `FileResponse` from `backend/resumes/<resume_filename>`.
   - Mirrors the existing sessions-resume pattern (`admin.js:442` `data-download="1"`) so `admin.js`'s download interceptor handles auth.
   - `admin_registrations` (`:342`) already returns `SELECT *` rows, so `state`/`country`/`resume_filename` ride along automatically.

### Frontend — profile page
7. **`frontend/profile.html`** — in `#profileEditMode` (after LinkedIn, `:272-275`): add a Location input + dropdown (`editLocation` / `editLocationResults`), styled like the search autocomplete.
8. **`frontend/js/profile.js`**
   - `enableProfileEdit` (`:182`) pre-fills the picker from `getProfile()` state/country.
   - `saveProfile` (`:212`) sends `state`/`country` when a location was picked (omit when untouched → optional).
   - `renderProfile` (`:51`) adds a `"State, Country"` row to the profile display card (icon + text, like the email/joined rows at `profile.html:217-229`).

### Frontend — admin registrations
9. **`frontend/admin.html:618`** — table header: add `Location` + `Resume` columns.
10. **`frontend/js/admin.js`** `renderRow` (`:611`):
    - Location cell: `"${state}, ${country}"` or `—`.
    - Resume cell: `View` link → `/api/admin/users/<email>/resume` with `data-download="1"` + `_blank`, or `—`.
    - Bump the empty-state `colspan` (`:605`) and jobs-detail `colspan` (`:632`) from 10 → 12.

## Tests & verification
11. `backend/tests/test_integration.py` (`TestUserLocation`, mirroring `TestAdminBackup` style):
    - `PUT /api/profile` with `state`/`country` persists; `GET /api/profile` returns them.
    - `/api/admin/registrations` includes `state`, `country`, `resume_filename`.
    - `/api/admin/users/{email}/resume`: non-admin 403, admin 200 (file), 404 when no resume.
12. Full suite (90 → ~93), `py_compile`, `node --check` on touched JS.
13. Manual: search-page picker still works; profile location picker behaves identically; save shows state/country on the card; admin registrations shows both columns and a working resume download.

## Deploy
- Only commit/push/deploy when the user explicitly asks.

## Relevant files
- `frontend/js/search.js` — location autocomplete to extract: `fetchCountries:1339`, `loadStates:1351`, `setupLocationSearch:1359`, `searchState:1379`, `selectLocation:1429`
- `frontend/js/profile.js` — `enableProfileEdit:182`, `saveProfile:212`, `renderProfile:51`
- `frontend/profile.html` — edit form `:246-294`, display rows `:217-241`
- `backend/db.py` — users table `:99-111`, migration block `:347`, `update_user_profile:1148`
- `backend/api/routes/profile.py` — `UpdateProfileRequest:19`, `profile_get:34`, `profile_update:61`
- `backend/api/routes/admin.py` — `admin_registrations:342`, `_check_admin:348`; new `users/{email}/resume`
- `frontend/admin.html:618` — registrations table header
- `frontend/js/admin.js` — `renderRow:611`, `colspan` `:605`/`:632`, sessions-resume pattern `:442`
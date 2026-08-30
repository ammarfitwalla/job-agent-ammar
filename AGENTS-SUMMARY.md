# job-agent-ammar — Session Summary (updated Aug 27 2026)

## Objective
- Ship the referral-network feature ("paste job link → get referred", Option 2 lean scope) end-to-end, verified with dummy accounts/links.
- Current focus: fix "complete profile button not working" — user attributes it to JS version cache (was fixed by version bump before).
- Deploy to Oracle ONLY on explicit go-ahead (still withheld).

## Critical Rules
- `backend/config.py` is bind-mounted on Oracle (`/home/ubuntu/job-agent/backend/config.py` → `/app/backend/config.py`) and now contains SMTP creds (`ammarfitwalla@gmail.com`, app password `wnbo yciv ihnb vmro`) + Groq key. **Never commit or push it.** Local and Oracle copies are now identical for EMAIL/Groq. `git add backend/` will stage it — always stage files explicitly.
- Oracle deploy: host `130.210.34.176`, user `ubuntu`, key `$env:USERPROFILE\.ssh\oracle.key`. Container `job-agent`. Deploy = scp → `docker cp` → `docker restart job-agent`. `job_agent.db` (~28MB) + `backend/resumes/` live inside container only.
- Remote repo: `https://github.com/ammarfitwalla/job-agent-ammar.git`. Verified reachable; container has outbound SMTP to smtp.gmail.com:587 (tested FROM the container, login+send OK).

## Auth / Email delivery (current root-cause knowledge)
- send-code flow: backend tries SMTP → on failure returns `fallback:true` + code → frontend retries via EmailJS (`service_hm8m45q`, `template_6hlgxz5`, key `wqGQqAkbZLnEpEOjq`) → **NEW**: if EmailJS also fails, the code is now displayed on-screen (`authFallbackCode` banner) and the flow proceeds anyway. This guarantees the auth flow never dead-ends on email delivery.
- CRITICAL FINDING: EmailJS is geo/IP-blocked from this region (Cloudflare HTTP 403 error code 1010). So EmailJS fallback alone never worked here. SMTP is the only reliable path. Local config previously had empty `EMAIL_PASSWORD` → `send-code` skipped SMTP → EmailJS blocked → **no code ever arrived → user could not verify → "complete profile" seemed broken.** Fixed: real SMTP creds now in local config.py (uncommitted, matches Oracle).
- Rate limit: 3/60s per email on send-code; 5/300s on verify-code.

## Frontend auth (two paths — keep in sync)
- index.html (main /app): search.js classic-script stepper auth CLIBS; search.js unconditionally overwrites window.showAuthModal/closeAuthModal/selectEmploymentStatus/addCustomCompany/selectCompany/authRegister (tail ~lines 2351-2359). auth.js guarded exports don't fight it. authSendCode + authVerifyCode + authRegister live in search.js.
- profile.html: auth.js module auth flow (promptSendCode → modal `authStep1` code entry + `authStep4` register). Auth refer_opt_in checkbox + invite banner present in BOTH index.html and profile.html step4.
- Both flows now: parse `?ref`/`?company` (invite), prefill company + banner + auto opt-in, register sends `refer_opt_in`+`invited_by`, show +5-credit toast. `prefillInviteDetails` defined in both search.js and auth.js (guarded export).
- `_EMPLOYMENT_LABELS`, `DEV_MODE`, `_MONTHLY_LIMIT` exposed on window by constants.js (classic script reads window._EMPLOYMENT_LABELS — fine, deferred module runs before any click).

## Versioning
- index.html + profile.html scripts `?v=16` (v=14→v=15→v=16 as cache-bust fixes). admin.html stays v=12. Bump on EVERY frontend change; stale HTML/JS cache is the recurring "button not working" cause.

## Tests
- `test_features` + `test_integration` TestIntegrationReferralNetworkFlow (11) = **61 passing**. Verified again: 11/11 referral integration tests pass.
- 7 pre-existing environmental failures (live-LLM keyword parsing, local scrape cache): test_linkedin_scraper (4), test_job_cache (1), test_role_recommendation (2).
- JS check: `node --check frontend/js/search.js` OK; ES modules → cp to `$env:TEMP\*.mjs` then `node --check`.
- Verify script (committed cc1fd1e): `python backend/scripts/verify_referral_network.py` → 28 checks pass (throwaway DB).
- SMTP verified live: auth.py login+send_message OK from local AND from inside Oracle container.

## Git state
- config.py NEVER staged. Untracked-at-repo-root scratch: AGENTS-SUMMARY.md, tmp_usage.json; untracked under backend/scripts: check_naukri_locations.py, test_migration.py, test_naukri_*.py — all intentionally left out.
- main commits: 61f8214 (pre-session), d814c05 (Option 2), cc1fd1e (verify script), 362be2f (complete-profile fixes v15), ba7eb3d (v16 + fallback-code + SMTP). All pushed.

## Current Task / Status
"Complete profile button not working" — likely closed: real cause was code never arriving (empty local SMTP + geo-blocked EmailJS). Fixed SMTP locally + on-screen fallback code + v=16 bump. Deployed code on Oracle is still OLD (never deployed d814c05+); user must hard-refresh (Ctrl+F5) when testing locally, or explicitly approve deploy for live.

## Next Move
1. User hard-refresh and retry send-code → code should arrive via SMTP (or visible on-screen).
2. If still broken after refresh, capture: which URL, browser console error, exact button behavior.
3. Pending: deploy Option 2 to Oracle (scp + docker cp + restart) only on approval. NVIDIA provider still planned-not-implemented.
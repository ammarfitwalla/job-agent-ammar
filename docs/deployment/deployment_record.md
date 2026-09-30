# JobAwn — Post-Registration Deployment Record

**Date:** 2026-09-07
**Domain:** `jobawn.com` (registered at Hostinger)
**Server:** `ubuntu@130.210.34.176` (Oracle Cloud, Ubuntu 22.04.5 LTS, public IP `130.210.34.176`)
**App:** `job-agent` Docker container (FastAPI/uvicorn) on port 7860

This document records the exact steps executed after the domain was registered, to bind
`jobawn.com` to the app via **nginx reverse proxy + Let's Encrypt TLS**, and to stop exposing
the raw app port publicly.

---

## Final architecture

```
Internet → nginx (Docker, :443 + :80) → appnet (user-defined bridge) → job-agent:7860 (loopback-only)
```

- nginx is the **only** public surface (443 TLS + 80 redirect).
- The app container binds to `127.0.0.1:7860` on the host only; nginx reaches it over the `appnet` bridge network by container name (`proxy_pass http://job-agent:7860`).

---

## Step-by-step executed

### Step 1 — Domain + DNS (Hostinger)

- Registered `jobawn.com` at Hostinger (WHOIS privacy included free).
- DNS zone kept at Hostinger (registrar DNS).
- Records in hPanel **DNS Management**:
  - `A` record, name `@` → `130.210.34.176` (TTL 600) — replaced Hostinger's parking IP.
  - `www` left as existing `CNAME → jobawn.com` (a host cannot have both CNAME and A; the CNAME follows the apex A record).
- Verified locally:
  ```powershell
  Resolve-DnsName jobawn.com    # A  → 130.210.34.176
  Resolve-DnsName www.jobawn.com # → jobawn.com → 130.210.34.176
  ```

### Step 2 — Firewall (needed before nginx so traffic could actually arrive)

- **Oracle VCN (console):** added two ingress rules — Source `0.0.0.0/0`, TCP, ports `80` and `443` — to the Default Security List.
- **Host iptables:** allowed 80/443, inserted directly before the final REJECT rule, and persisted:
  ```bash
  sudo iptables -I INPUT 5 -p tcp --dport 80 -j ACCEPT
  sudo iptables -I INPUT 5 -p tcp --dport 443 -j ACCEPT
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y iptables-persistent
  sudo netfilter-persistent save
  ```

### Step 3 — nginx reverse proxy (Docker)

Important detail: the **default docker `bridge` network does not resolve container names**,
so nginx could not use `proxy_pass http://job-agent:7860` there. Fix: a user-defined bridge
network `appnet`, with the app container attached to it (non-disruptive).

- Create network + attach app:
  ```bash
  sudo docker network create appnet
  sudo docker network connect appnet job-agent
  ```
- Config `/home/ubuntu/job-agent/nginx.conf` (mounted read-only into nginx):
  ```nginx
  server {
      listen 80;
      server_name jobawn.com www.jobawn.com;

      location /.well-known/acme-challenge/ {
          root /var/www/certbot;
      }
      return 301 https://$host$request_uri;
  }

  server {
      listen 443 ssl;
      http2 on;
      server_name jobawn.com www.jobawn.com;

      ssl_certificate     /etc/letsencrypt/live/jobawn.com/fullchain.pem;
      ssl_certificate_key /etc/letsencrypt/live/jobawn.com/privkey.pem;

      location /.well-known/acme-challenge/ {
          root /var/www/certbot;
      }

      location / {
          proxy_pass http://job-agent:7860;
          proxy_set_header Host $host;
          proxy_set_header X-Real-IP $remote_addr;
          proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
          proxy_set_header X-Forwarded-Proto $scheme;
          proxy_http_version 1.1;
          proxy_set_header Upgrade $http_upgrade;
          proxy_set_header Connection "upgrade";
      }
  }
  ```
- Run container:
  ```bash
  sudo docker run -d --name nginx --restart=unless-stopped --network appnet \
    -p 80:80 -p 443:443 \
    -v /etc/letsencrypt:/etc/letsencrypt:ro \
    -v /home/ubuntu/job-agent/nginx.conf:/etc/nginx/conf.d/default.conf:ro \
    -v /var/www/certbot:/var/www/certbot:ro \
    nginx:stable-alpine
  ```
- The webroot volume (`/var/www/certbot`) is required so the ACME HTTP-01 challenge is served from inside the container.

### Step 4 — TLS via certbot / Let's Encrypt

```bash
sudo apt-get install -y certbot
sudo mkdir -p /var/www/certbot
sudo certbot certonly --webroot \
  --webroot-path /var/www/certbot \
  -d jobawn.com -d www.jobawn.com \
  --agree-tos --email ammarfitwalla@gmail.com --non-interactive
```

- Cert issued: `/etc/letsencrypt/live/jobawn.com/` (`fullchain.pem`, `privkey.pem`, …).
- Confirmed `ssl_certificate` paths in nginx config, then reloaded without downtime:
  ```bash
  sudo docker exec nginx nginx -t      # syntax ok
  sudo docker exec nginx nginx -s reload
  ```
- Auto-renew already scheduled and active:
  ```bash
  systemctl is-enabled certbot.timer   # enabled
  systemctl is-active  certbot.timer   # active
  sudo certbot renew --dry-run         # PASSED ("all simulated renewals succeeded")
  ```
- Cert validity: `2026-09-07` → `2026-12-06` (90-day), subject `CN = jobawn.com`.

### Step 5 — Make the app port 7860 internal-only

The app has **no volumes** — app files + DB live in the container's writable layer, so state
was captured before recreation:

```bash
# Snapshot the running container (preserves DB + deployed files + restart policy)
sudo docker commit job-agent job-agent:snapshot-2026-09-07

# Extra safety copy of the DB
sudo docker cp job-agent:/app/backend/job_agent.db ~/job_agent.db.snapshot-2026-09-07

# Recreate bound to loopback only, on appnet (nginx name-resolution keeps working)
sudo docker stop job-agent && sudo docker rm job-agent
sudo docker run -d --name job-agent --restart=unless-stopped --network appnet \
  -p 127.0.0.1:7860:7860 \
  job-agent:snapshot-2026-09-07 \
  uvicorn api.main:app --host 0.0.0.0 --port 7860
```

Result: `ss` shows `127.0.0.1:7860` only; `http://130.210.34.176:7860/health` times out from the internet.

---

## Verification results (2026-09-07)

| Check | Result |
|---|---|
| `https://jobawn.com/` | **200** — JobAwn landing (SSL verify OK) |
| `https://jobawn.com/app` | 200 — `JobAwn` title |
| `https://jobawn.com/admin` | 200 |
| `https://jobawn.com/js/auth.js` | 200 |
| `https://www.jobawn.com/` | **200** (CNAME) |
| `http://jobawn.com/` | **301 → https://jobawn.com/** |
| `http://130.210.34.176:7860/health` | refused/timeout (internal-only) |
| `http://127.0.0.1:7860/health` (host) | `{"status":"ok","scrapers_configured":["adzuna","remoteok","indeed"]}` |

---

## Container / host inventory

| Item | Value |
|---|---|
| nginx container | name `nginx`, image `nginx:stable-alpine`, restart `unless-stopped`, network `appnet`, publishes 80/443 |
| app container | name `job-agent`, image `job-agent:snapshot-2026-09-07` (previously `job-agent:latest`), restart `unless-stopped`, network `appnet`, publishes `127.0.0.1:7860`, cmd `uvicorn api.main:app --host 0.0.0.0 --port 7860` |
| appnet network | user-defined bridge (container-name DNS) |
| nginx config source | `/home/ubuntu/job-agent/nginx.conf` (LF, mounted read-only) |
| cert + webroot | `/etc/letsencrypt/live/jobawn.com/`, `/var/www/certbot` |
| iptables | ACCEPT 80/443 persisted via `iptables-persistent` |
| firewall (cloud) | Oracle VCN Security List: TCP 80 + 443 from `0.0.0.0/0` |

---

## Rollback notes

- **nginx removal:** `sudo docker rm -f nginx` — app stays up, but raw `IP:7860` is loopback-only after Step 5, so to re-publicize the app you'd also recreate it with `-p 0.0.0.0:7860:7860`.
- **App to pre-Step-5 state:** `sudo docker run -d --name job-agent --restart=unless-stopped --network appnet -p 0.0.0.0:7860:7860 job-agent:latest uvicorn api.main:app --host 0.0.0.0 --port 7860`.
- **DB safety copy:** `~/job_agent.db.snapshot-2026-09-07` (47M) and image `job-agent:snapshot-2026-09-07` are retained.
- **iptables:** remove with `sudo iptables -D INPUT -p tcp --dport 80 -j ACCEPT` (and 443) — restores the old REJECT-everything-else posture.
- **Domain:** DNS A/CNAME + Hostinger login are with the owner; WHOIS privacy is free and enabled.

---

## Follow-ups / notes

- Rename references to the old brand are handled app-side (rebrand to JobAwn done separately).
- Email sending: Brevo code removed 2026-09-07 (`utils/emailer.py` + `/api/email/report` route) — active senders are SMTP (`smtp_sender.py`) for backend OTP/backups and EmailJS (frontend OTP fallback). localStorage keys (`jobagent_*`) intentionally left unchanged.
- Next app deploys continue via the established `scp → docker cp → py_compile → docker restart job-agent` flow — the container now shares no volume, so step order stays snapshot-safe.

---

## Deployment entry — 2026-09-07 (evening)

Pushed via the `scp → docker cp → py_compile → docker restart` flow from local working tree, **excluding `backend/config.py`** (server copy untouched).

- **Pre-deploy rollback image:** `job-agent:snapshot-2026-09-07-pre-deploy` (docker commit of the running container before files were copied).
- **Backend:** rate limiting (`utils/rate_limiter.py` hardened — lock + TTL sweep, `utils/client_ip.py` new), split rate limits across routes (`api/routes/{auth,events,joblink,jobs,leads,referrals,resume,roles,scrape,users,visits}.py`), Brevo removal completed (`api/routes/email.py` + `utils/emailer.py` deleted from container).
- **Frontend:** admin user-modal status/company fix (`admin.html`, `js/admin.js`), pagination overflow / windowing fix + page clamp (`js/search.js`), auth `search_id` carry-over fix (`js/auth.js`).
- Verified post-restart: container `Up`, loopback `/health` 200, public `https://jobawn.com/health` 200, new pagination/auth/admin markers served, `/api/email/report` → 404.
---

## Deployment entry - 2026-09-30 (weekly engagement email)

Deployed via the established `scp -> docker cp -> md5 verify -> docker restart` flow from the
local working tree. **Uncommitted at the time of deploy** (local `git status` still shows the
engagement files as modified/untracked; commit pending owner approval).

**Files copied into the container** (all 6 md5sums matched local before restart):

| File | Change |
|---|---|
| `db.py` | `users.email_opt_out` migration, `idx_visits_email`, `get_engagement_recipients()`, `get_cached_roles()`, `set_user_email_opt_out()` |
| `scheduler.py` | engagement producer: profile-only anchor, country resolution, role matching, city/state/country cache ladder, 3-way email dispatch |
| `emails/templates.py` | `build_engagement()` (honest counts), `build_engagement_location_prompt()` (new), `build_engagement_fallback()` (generic) |
| `emails/unsubscribe.py` | **new** - HMAC-SHA256 signed opt-out links |
| `api/routes/email_prefs.py` | **new** - `GET /api/email/unsubscribe` |
| `api/main.py` | route registration + public-path allowlist |
| `config.py` | **only** the `ENGAGEMENT_*` block appended (secrets untouched) |

**Pre-deploy rollback:** `/home/ubuntu/job-agent-deploy/pre-engagement-backup.tar.gz`
(previous `db.py`, `scheduler.py`, `emails/templates.py`, `api/main.py`, `config.py`) plus
`/app/backend/config.py.bak-engagement`. The deploy dir is **not** a git repo, so these
file copies are the only record - `backend/config.py` and the engagement sources are
mirrored into `/home/ubuntu/job-agent-deploy/backend/` so a container rebuild keeps them.

**Migration applied at boot:** `users.email_opt_out` column + `idx_visits_email` index. Clean
startup, zero tracebacks.

**Verified before enabling:** migration present, unsubscribe sign/validate against the real
prod `JWT_SECRET` (valid link accepted, tampered signature rejected), public route through
nginx returning HTTP 200 on a signed link and HTTP 400 on a bad one, `/health` 200, and
`0` engagement rows in the queue while the flag was off.

**Go-live:** `ENGAGEMENT_ENABLED = True` (dormant 7d, min age 3d, 20/pass, 168h cache,
30-job cap). On restart the producer logged `Queued 16 engagement email(s)` and
`Queue drained - sent 16 of 16` (all `attempts=1`, no retries).

**Known first-run characteristic:** all 16 went out as the strictly generic
*"Fresh roles are waiting for you"*. Not a matching failure - the dormant cohort has no market
signal: only 338 of 1435 `visits` rows carry a `user_email`, and 1097 rows have a country with
**no** `user_email` (captured while logged out, never attributed to a person), while only 2 of
24 users have `users.country` set. 7 of the 16 do have roles that resolve cleanly to cached
roles with 30 jobs each (`Software Enginner`->`Software Engineer`, `Backend Developer Intern`->`Backend Developer`,
`Node js developer`->`Node.js Developer`) - blocked purely on the market. Owner accepted the
generic send for week 2026-W39.

**Follow-up (not engagement-code scope):** capture market at signup or attribute logged-out
visits to the user, so the personalized branch can fire for the dormant cohort in a later week.

**Idempotency confirmed:** the next 5-minute worker pass enqueued nothing; 16 dormant users
remain but 0 are eligible for `2026-W39` because of the `engage:{week}:{email}` dedup key.
Public `https://jobawn.com/health` 200 and bad-sig unsubscribe 400 verified from off-host.

---

## Deployment entry - 2026-09-30 (session lifetime 24h -> 48h)

`JWT_ACCESS_TOKEN_MINUTES` `1440` -> `2880` in `backend/config.py` (git-ignored; the server
copy is the source of truth) and `backend/config.example.py` (tracked). Commit `46277c0`.

- **No frontend change needed:** `frontend/js/api.js` decodes the JWT `exp` claim rather than
  hardcoding a 24h window, and the login cookie's `max_age` derives from the same setting
  (`api/routes/auth.py`), so both follow the config automatically.
- **Existing sessions are unaffected:** `exp` is fixed at issue time, so only newly issued
  tokens carry the 48h window. `JWT_SECRET` was not rotated, so no one is logged out.
- Verified: prod config reads `2880`; a freshly minted token's `exp - iat` is 48h; public
  `/health` 200; 29 auth/token tests pass; full suite 322 passed (same 6 pre-existing
  unrelated failures). No engagement re-send on restart (weekly dedup held).
- **Backup:** `/app/backend/config.py.bak-1440`. Deploy-dir `config.py` re-synced so a
  container rebuild keeps the new value.
- Engagement dormancy is unaffected: it is driven by page-level `visits`, not token lifetime.

---

## Deployment entry - 2026-09-30 (admin Sessions: user location column)

Commit `8b253be`. Files: `backend/api/routes/admin.py`, `frontend/js/admin.js`,
`frontend/admin.html`, `backend/tests/test_admin_sessions_geo.py` (all 3 runtime
files md5-verified in-container before restart).

**Why:** the Sessions table only showed `sessions.location` (what the user typed
into the search box). The `user_country`/`user_city`/`user_region` columns already
existed but were empty - the scrape-time geo only fires when the request carried a
client IP (19/193 prod sessions). The app had already geolocated the same visitor
via the visits tracker, so the data existed but was never joined in.

**Change:** `GET /api/admin/sessions` now returns `user_location` plus
`user_location_source`, resolved session-geo -> user's latest geolocated visit ->
visit for that session's IP. Two grouped queries build the maps (no N+1).
`admin.js` gained a "User Location" column beside the renamed "Searched Location",
sortable and searchable; row/empty colspans 10 -> 11.

**Verified:** 14 new tests pass; full suite 336 passed with the same 6 known
pre-existing failures (4 `test_linkedin_scraper.py`, 2 `test_role_recommendation.py`).
`tests/test_scrape_controls.py::test_slow_nonempty_batch_is_not_stalled` is
**flaky, not a regression** - verified 5 failures in 8 runs on a clean tree with
these changes stashed. Live endpoint returns HTTP 200 with 193 sessions, 70 with
`user_location` (19 own geo, 51 via visit), field present on every row; served
`/js/admin.js` contains the new column. Zero tracebacks after restart.

**Known limit:** the other 123 sessions are legacy rows from 2026-09-25/26 with
neither `user_email` nor `ip_address` recorded, so they render as a dash. 5 more
have an email whose visits carry no geo. Not attributable without guessing.

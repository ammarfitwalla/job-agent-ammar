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
- `noreply@jobagent.brevo.com` (Brevo sender) and localStorage keys (`jobagent_*`) were intentionally left unchanged.
- Next app deploys continue via the established `scp → docker cp → py_compile → docker restart job-agent` flow — the container now shares no volume, so step order stays snapshot-safe.
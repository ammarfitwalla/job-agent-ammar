# Deployment Plan: Bind a Domain via Nginx Reverse Proxy + TLS

Status: **Final (ready to execute)** — **✅ EXECUTED 2026-09-07**
Date: 2026-09-02 · **Updated 2026-09-07 — domain registered → `jobawn.com`**
Server: `ubuntu@130.210.34.176` (Oracle Cloud, Ubuntu 22.04.5 LTS, public IP `130.210.34.176`)
App: `job-agent` Docker container (FastAPI/uvicorn), exposing `0.0.0.0:7860->7860`

Domain: **`jobawn.com`** — registered **2026-09-07** at **Hostinger** (WHOIS privacy included free).

## Goal
Visit `https://jobawn.com` → nginx (Docker) on 80/443 → reverse-proxy → `job-agent` on internal-only `127.0.0.1:7860`, with real TLS (Let's Encrypt) and HTTP→HTTPS redirect.

---

## Decided / Locked
| Item | Choice |
|---|---|
| Binding approach | **Option A — nginx reverse proxy + TLS** |
| nginx install | **Docker container** on the existing `bridge` network |
| Raw port exposure | **7860 internal-only** after nginx is live |
| Cockpit (9090) | **SSH-tunnel only** — do NOT expose publicly (follow-up: optional proxied + auth) |
| DNS zone location | **Registrar DNS** (not OCI DNS) |
| Provider for domain | **Hostinger** — `jobawn.com` registered 2026-09-07; You hold billing; I configure DNS |
| VCN 80/443 | **You** open in Oracle Cloud Console |
| Host `iptables` 80/443 | **I** add ACCEPT rules |
| TLS | **certbot / Let's Encrypt**, 90-day cert, daily auto-renew |

---

## Current-state facts (re-verified 2026-09-07)
- Ubuntu 22.04.5 LTS; user `ubuntu`; public IP `130.210.34.176` (egress IP confirmed).
- `job-agent` still publishes `0.0.0.0:7860` (IPv4 + IPv6).
- Container: image `job-agent:latest`; restart `unless-stopped`; cmd `uvicorn api.main:app --host 0.0.0.0 --port 7860`; **no volume binds**; bridge IP `172.17.0.2`.
- ⚠️ **No volumes** → app files and `backend/job_agent.db` live in the container's writable layer. **Back up / snapshot before any container recreation** (see Phase 5).
- Docker networks: `bridge` (app here), `host`, `none`.
- **nginx not installed**, **certbot not installed**; ports **80/443 free**.
- Cockpit (9090) still bound `*:9090` but net-blocked; keep SSH-tunnel-only.
- Egress DNS resolves (good for certbot + registrar).
- Host `iptables` INPUT: ACCEPT established / icmp / lo / SSH(22); all else → `REJECT` (rules at positions 1–5 → insert 80/443 ACCEPT at position 5).

---

## Phase 0 — ✅ COMPLETE: domain registered
- **`jobawn.com`** registered **2026-09-07** at **Hostinger** (bearer/holder: You).
- WHOIS privacy protection **included free** and enabled at registration — no separate "protection" upsell required.
- DNS will live at the **registrar** (Hostinger), per decision table. I configure the records there.

---

## Phase 1 — Open firewall layers (80/443 from internet)
Two independent layers must both permit 80/443.

### 1A. Oracle Cloud VCN ingress — YOU (web console)
1. Console → **Networking → Virtual Cloud Networks** → your VCN → **Security Lists** → Default Security List → **Add Ingress Rules**.
2. Add TWO rules: Source `0.0.0.0/0`, IP Protocol **TCP**, Destination Port **80** and **443** (mirror the existing SSH rule shape).

### 1B. Host OS iptables — ME
```bash
sudo iptables -I INPUT 5 -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 5 -p tcp --dport 443 -j ACCEPT
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y iptables-persistent
```
(INSERT at position 5 = before the final `REJECT`; persistent across reboots.)

---

## Phase 2 — DNS A-record — ME (or registrar dashboard)
- Add an **A record**: `@` (`jobawn.com`) → `130.210.34.176`; optionally `www.jobawn.com` → same IP.
- Propagation typically < 1 hr.
- Verify locally: `Resolve-DnsName jobawn.com`.

---

## Phase 3 — nginx (Docker container) — ME
1. Get the app container's bridge IP and name:
   ```bash
   sudo docker inspect job-agent --format '{{.Name}} {{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'
   ```
2. Write `nginx.conf` (placeholder `JOB_AGENT_IP`):
   ```nginx
   server {
       listen 80;
       server_name jobawn.com www.jobawn.com;

       location / {
           proxy_pass http://JOB_AGENT_IP:7860;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
           proxy_http_version 1.1;
           proxy_set_header Upgrade $http_upgrade;   # harmless; future SSE/streaming
           proxy_set_header Connection "upgrade";
       }
   }
   ```
   > **Note:** App is **FastAPI** (not Gradio) — the websocket `Upgrade`/`Connection` headers are harmless and kept for future SSE/streaming. The important lines are `proxy_set_header Host` + the `X-Forwarded-*` headers.
3. Run the container:
   ```bash
   sudo docker run -d --name nginx --network bridge \
     -p 80:80 -p 443:443 \
     -v /etc/letsencrypt:/etc/letsencrypt:ro \
     -v /home/ubuntu/job-agent/nginx.conf:/etc/nginx/conf.d/default.conf:ro \
     nginx:stable-alpine
   ```

---

## Phase 4 — TLS via certbot — ME
```bash
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y certbot
sudo mkdir -p /var/www/certbot
sudo certbot certonly --webroot \
  --webroot-path /var/www/certbot \
  -d jobawn.com -d www.jobawn.com
```
- Add `ssl_certificate` + `ssl_certificate_key` to the nginx config:
  ```
  ssl_certificate     /etc/letsencrypt/live/jobawn.com/fullchain.pem;
  ssl_certificate_key /etc/letsencrypt/live/jobawn.com/privkey.pem;
  ```
- Add a `server` block listening on 443 with the certs.
- Make the `:80` block redirect: `return 301 https://$host$request_uri;`
- Copy the updated `nginx.conf` into the container and reload:
  ```bash
  sudo docker cp nginx.conf nginx:/etc/nginx/conf.d/default.conf
  sudo docker exec nginx nginx -s reload
  ```

---

## Phase 5 — Make 7860 internal-only — ME
Once nginx is verified serving HTTPS. Because the app has **no volumes** (DB lives in the container only), snapshot first:

```bash
# 1) Snapshot the running container (preserves DB + deployed files + restart policy)
sudo docker commit job-agent job-agent:snapshot-2026-09-07
# 2) Belt-and-braces: pull a DB copy out too
sudo docker cp job-agent:/app/backend/job_agent.db ~/job_agent.db.snapshot-2026-09-07

# 3) Recreate bound to loopback only (same name, restart policy, image, cmd)
sudo docker stop job-agent
sudo docker rm job-agent
sudo docker run -d --name job-agent --restart=unless-stopped \
  -p 127.0.0.1:7860:7860 \
  job-agent:snapshot-2026-09-07 \
  uvicorn api.main:app --host 0.0.0.0 --port 7860

# 4) Verify the app is still healthy
curl -s http://127.0.0.1:7860/health
```
- Result: public `IP:7860` no longer reachable; only nginx on 80/443 is public (nginx reaches app over the bridge network at `172.17.0.2:7860`).

---

## Phase 6 — Verify + auto-renew — ME
1. `https://jobawn.com` loads app; `http://jobawn.com` → 301 to `https://`.
2. App loads fully over the proxy (all static assets, JS modules, API responses).
3. `sudo certbot renew --dry-run` passes.
4. Enable auto-renew timer:
   ```bash
   sudo systemctl enable certbot.timer
   sudo systemctl start certbot.timer
   ```
5. (Optional follow-up) proxy Cockpit behind nginx + auth — **not now**; keep tunnel-only.

---

## Rollback
- Stop/remove nginx container → `job-agent` still reachable on `IP:7860` (before Phase 5) or restore prior `0.0.0.0` binding (after Phase 5).
- Remove added iptables rules: `sudo iptables -D INPUT -p tcp --dport 80 -j ACCEPT` (and 443).
- Remove DNS A-record / cert.

---

## Out of scope / deferred
- Cockpit public exposure (keep SSH-tunnel-only).
- Phase 5 exact image rebuild — will capture `job-agent` run args at execution time.

---

## To proceed (remaining owner action — the one blocker)
1. **Confirm VCN 80/443 ingress is opened** in Oracle Cloud Console (Phase 1A): Networking → VCN → Security Lists → Default Security List → **Add Ingress Rules** — two rules, Source `0.0.0.0/0`, TCP **80** and **443**.
2. Optionally confirm Hostinger DNS panel access so I can add the `jobawn.com` A-record (`@` → `130.210.34.176`).

Everything from Phase 1B onward is mine to execute once #1 is done.

---

## ✅ Completion log (2026-09-07)
| Phase | Result |
|---|---|
| 0 | Domain registered: `jobawn.com` @ Hostinger |
| 1A | VCN ingress 80/443 — done (confirmed externally, `http://jobawn.com` → 200) |
| 1B | Host iptables ACCEPT 80/443, persisted via `iptables-persistent` |
| 2 | DNS: A `@`→`130.210.34.176` (TTL 600), `www` stays CNAME→`jobawn.com`; propagation confirmed |
| 3 | nginx:stable-alpine on **`appnet`** (user-defined bridge; default `bridge` does NOT resolve container names) — `proxy_pass http://job-agent:7860`; webroot volume mounted; `--restart=unless-stopped` |
| 4 | certbot (let's encrypt) cert for `jobawn.com` + `www.jobawn.com`; HTTP→301→HTTPS; `certbot.timer` enabled (daily ~10:07 UTC); `renew --dry-run` PASSED |
| 5 | Snapshot `job-agent:snapshot-2026-09-07` + DB copy `~/job_agent.db.snapshot-2026-09-07` (47M); app recreated loopback-only `-p 127.0.0.1:7860:7860` on `appnet`; public `IP:7860` unreachable |
| 6 | `https://jobawn.com` 200 (app/admin/assets), `http://` 301, `/health` ok, cert valid to 2026-12-06 |

**Live layout:** internet → nginx:443/80 (only public surface) → `appnet` → `job-agent:7860` (loopback-only).

**Notes for later:** host `iptables` 80/443 ACCEPT rules are runtime (persisted via netfilter-persistent); `~/job_agent.db.snapshot-2026-09-07` and image `job-agent:snapshot-2026-09-07` retained as pre-Phase-5 rollback; `job-agent:latest` retains the pre-recreation payload.

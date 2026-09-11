# JWT Auth — Production Deploy Runbook

**Server:** `ubuntu@130.210.34.176` (Oracle Cloud), nginx -> Docker `job-agent:7860`
**Domain:** `https://jobawn.com`

The JWT_SECRET is **hardcoded in `backend/config.py`** (git-ignored, never committed).
Because it is baked into the file, this deploy uses the normal
`scp -> docker cp -> py_compile -> docker restart` flow — **no env var, no container recreate**.

---

## 1. Pre-deploy (local)

- Keep `backend/config.py` out of git (`git rm --cached` already done; file remains on disk).
- Confirm JWT block is present in the copy you ship:
  ```python
  JWT_SECRET = os.environ.get("JWT_SECRET", "<hardcoded-secret>")
  JWT_ALLOW_DEV_SECRET = os.environ.get("JWT_ALLOW_DEV_SECRET", "") == "1"
  JWT_ACCESS_TOKEN_MINUTES = int(os.environ.get("JWT_ACCESS_TOKEN_MINUTES", "1440"))
  ```
- Do NOT set `JWT_ALLOW_DEV_SECRET` on the server (docs stay admin-locked; only the real secret is used).

## 2. Rollback snapshot

```bash
sudo docker commit job-agent job-agent:rollback-pre-jwt
```

## 3. Ship backend files

From your local tree, copy the JWT change set (frontend too, see step 5):

```bash
scp backend/... ubuntu@130.210.34.176:~/jwt-deploy/   # or scp individual files
```

```bash
sudo docker cp ~/jwt-deploy/api/main.py                 job-agent:/app/backend/api/main.py
sudo docker cp ~/jwt-deploy/api/deps.py                 job-agent:/app/backend/api/deps.py
sudo docker cp ~/jwt-deploy/api/routes/auth.py          job-agent:/app/backend/api/routes/auth.py
sudo docker cp ~/jwt-deploy/api/routes/profile.py       job-agent:/app/backend/api/routes/profile.py
sudo docker cp ~/jwt-deploy/api/routes/saved_jobs.py    job-agent:/app/backend/api/routes/saved_jobs.py
sudo docker cp ~/jwt-deploy/api/routes/referrals.py     job-agent:/app/backend/api/routes/referrals.py
sudo docker cp ~/jwt-deploy/api/routes/users.py         job-agent:/app/backend/api/routes/users.py
sudo docker cp ~/jwt-deploy/api/routes/admin.py         job-agent:/app/backend/api/routes/admin.py
sudo docker cp ~/jwt-deploy/utils/jwt.py                job-agent:/app/backend/utils/jwt.py
sudo docker cp ~/jwt-deploy/db.py                       job-agent:/app/backend/db.py
```

## 4. config.py — merge, don't blindly overwrite

The server's `config.py` holds your other real secrets (source of truth).

- If the local copy is known-identical apart from the JWT block, `docker cp` it wholesale:
  ```bash
  sudo docker cp ~/jwt-deploy/backend/config.py job-agent:/app/backend/config.py
  ```
- Otherwise, pull the server copy, paste in the JWT block above, push it back:
  ```bash
  sudo docker cp job-agent:/app/backend/config.py ~/config.py.prod
  # edit locally, then:
  sudo docker cp ~/config.py.prod job-agent:/app/backend/config.py
  ```
  Skipping this causes an `ImportError` at startup (`JWT_ALLOW_DEV_SECRET`, `JWT_ACCESS_TOKEN_MINUTES`).

## 5. Ship frontend files

```bash
sudo docker cp ~/jwt-deploy/frontend/js/api.js          job-agent:/app/frontend/js/api.js
sudo docker cp ~/jwt-deploy/frontend/js/auth.js         job-agent:/app/frontend/js/auth.js
sudo docker cp ~/jwt-deploy/frontend/js/utils.js        job-agent:/app/frontend/js/utils.js
sudo docker cp ~/jwt-deploy/frontend/js/profile.js      job-agent:/app/frontend/js/profile.js
sudo docker cp ~/jwt-deploy/frontend/js/jobs.js         job-agent:/app/frontend/js/jobs.js
sudo docker cp ~/jwt-deploy/frontend/js/referrals.js    job-agent:/app/frontend/js/referrals.js
sudo docker cp ~/jwt-deploy/frontend/js/search.js       job-agent:/app/frontend/js/search.js
sudo docker cp ~/jwt-deploy/frontend/js/admin.js        job-agent:/app/frontend/js/admin.js
sudo docker cp ~/jwt-deploy/frontend/index.html         job-agent:/app/frontend/index.html
sudo docker cp ~/jwt-deploy/frontend/profile.html       job-agent:/app/frontend/profile.html
sudo docker cp ~/jwt-deploy/frontend/admin.html         job-agent:/app/frontend/admin.html
```

## 6. Syntax check inside the container

```bash
sudo docker exec job-agent python -m py_compile \
  /app/backend/api/main.py /app/backend/utils/jwt.py /app/backend/api/deps.py \
  /app/backend/api/routes/auth.py /app/backend/api/routes/profile.py \
  /app/backend/api/routes/saved_jobs.py /app/backend/api/routes/referrals.py \
  /app/backend/api/routes/users.py /app/backend/api/routes/admin.py /app/backend/db.py
```

## 7. Restart

```bash
sudo docker restart job-agent
```

## 8. Verify

```bash
sudo docker ps                                   # Up
curl http://127.0.0.1:7860/health                # {"status":"ok",...}
curl http://127.0.0.1:7860/docs                  # 401 (admin-locked)
curl https://jobawn.com/health                   # 200 through nginx
```

- Browser: `/admin` -> OTP login works; save a job -> `saved` (token flow OK).
- Tests (local): `cd backend; $env:JWT_ALLOW_DEV_SECRET="1"; python -m unittest tests.test_integration tests.test_features`

---

## Rollback

```bash
# restore snapshot (recreates container with pre-deploy state)
sudo docker run -d --name job-agent --restart=unless-stopped --network appnet \
  -p 127.0.0.1:7860:7860 \
  job-agent:rollback-pre-jwt uvicorn api.main:app --host 0.0.0.0 --port 7860
sudo docker rm -f <old-job-agent-if-any>
```
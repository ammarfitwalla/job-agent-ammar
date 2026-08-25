# Oracle Cloud Deployment Commands

## Prerequisites
- SSH key at `%USERPROFILE%\.ssh\oracle.key`
- Instance IP: `130.210.34.176`
- User: `ubuntu`

## One-liner Variables (copy into terminal first)

```powershell
$KEY = "$env:USERPROFILE\.ssh\oracle.key"
$HOST = "ubuntu@130.210.34.176"
```

## SSH into instance

```powershell
ssh -i $KEY $HOST
```

## SCP files to instance

```powershell
# Single file
scp -i $KEY backend/match_engine/resume_data.py $HOST:/home/ubuntu/job-agent/backend/match_engine/resume_data.py

# Single file (config - bind mounted so only host copy matters)
scp -i $KEY backend/config.py $HOST:/home/ubuntu/job-agent/backend/config.py
```

## Copy files into running container

> Files baked into the Docker image need `docker cp`. Bind-mounted files (like `config.py`) update instantly.

```powershell
# Copy file into container
ssh -i $KEY $HOST "sudo docker cp /home/ubuntu/job-agent/backend/match_engine/resume_data.py job-agent:/app/backend/match_engine/resume_data.py"

# Restart container to pick up changes
ssh -i $KEY $HOST "sudo docker restart job-agent"
```

## Restart container

```powershell
ssh -i $KEY $HOST "sudo docker restart job-agent"
```

## Check container logs

```powershell
# Last 100 lines
ssh -i $KEY $HOST "sudo docker logs job-agent --tail 100 2>&1"

# Filter for prewarm
ssh -i $KEY $HOST "sudo docker logs job-agent --tail 100 2>&1 | grep PREWARM"

# Filter for errors
ssh -i $KEY $HOST "sudo docker logs job-agent --tail 100 2>&1 | grep -i 'failed\|error\|resume'"
```

## Verify Python imports inside container

```powershell
# Check resume_data loads without error
ssh -i $KEY $HOST "echo 'import match_engine.resume_data; print(repr(match_engine.resume_data.RESUME_TEXT))' | sudo docker exec -i job-agent python"

# Check relevance_engine import chain
ssh -i $KEY $HOST "echo 'from match_engine.relevance_engine import role_match_count; print(role_match_count(chr(112)+chr(121)+chr(116)+chr(104)+chr(111)+chr(110), [chr(100)+chr(97)+chr(116)+chr(97)]))' | sudo docker exec -i job-agent python"
```

## Edit config on server (sed)

```powershell
# Enable scheduler
ssh -i $KEY $HOST "sudo docker exec job-agent sed -i 's/SCHEDULER_ENABLED = False/SCHEDULER_ENABLED = True/' /app/backend/config.py"
```

## Check what's bind-mounted

```powershell
ssh -i $KEY $HOST "sudo docker inspect job-agent --format '{{json .Mounts}}'"
```

## Full rebuild + deploy flow

```powershell
# 1. Copy all backend files
scp -i $KEY -r backend/* $HOST:/home/ubuntu/job-agent/backend/

# 2. Copy files into running container (for baked files)
ssh -i $KEY $HOST "sudo docker cp /home/ubuntu/job-agent/backend/match_engine/resume_data.py job-agent:/app/backend/match_engine/resume_data.py"

# 3. Restart
ssh -i $KEY $HOST "sudo docker restart job-agent"

# 4. Verify
ssh -i $KEY $HOST "sudo docker logs job-agent --tail 20 2>&1"
```

## Notes
- `config.py` is **bind-mounted** from host — edits on host reflect immediately, no container restart needed for config changes
- `resume_data.py` is **baked into image** — requires `docker cp` + restart
- Idle prevention cron runs `curl -s http://localhost:7860/health` every 5 min to prevent Oracle from reclaiming the instance

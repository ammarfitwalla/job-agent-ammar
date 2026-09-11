#!/bin/bash
# Deploy job-agent to Oracle Cloud Always Free ARM instance
# Usage: bash deploy-oracle.sh <INSTANCE_IP> <SSH_KEY_PATH>
# Example: bash deploy-oracle.sh 129.153.xx.xx ~/.ssh/id_rsa

set -e

INSTANCE_IP="${1:?Usage: bash deploy-oracle.sh <INSTANCE_IP> <SSH_KEY_PATH>}"
SSH_KEY="${2:-~/.ssh/id_rsa}"
REMOTE_USER="ubuntu"
REMOTE_DIR="/home/$REMOTE_USER/job-agent"

echo "=== Deploying to $INSTANCE_IP ==="

# 1. Install Docker on remote
echo "[1/6] Installing Docker..."
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$REMOTE_USER@$INSTANCE_IP" << 'REMOTE'
sudo apt-get update -qq
sudo apt-get install -y -qq docker.io docker-compose-v2
sudo usermod -aG docker $USER
sudo systemctl enable docker
sudo systemctl start docker
REMOTE

# 2. Create remote directory
echo "[2/6] Creating remote directory..."
ssh -i "$SSH_KEY" "$REMOTE_USER@$INSTANCE_IP" "mkdir -p $REMOTE_DIR"

# 3. Copy files
echo "[3/6] Copying files..."
scp -i "$SSH_KEY" -r \
    Dockerfile \
    frontend/ \
    backend/ \
    "$REMOTE_USER@$INSTANCE_IP:$REMOTE_DIR/"

# 4. Create config.py on remote (from example, user edits secrets later)
echo "[4/6] Setting up config..."
ssh -i "$SSH_KEY" "$REMOTE_USER@$INSTANCE_IP" << REMOTE
cd $REMOTE_DIR
if [ ! -f backend/config.py ]; then
    cp backend/config.example.py backend/config.py
    echo "Created config.py from example — edit with your API keys"
fi
REMOTE

# 5. Build and run
echo "[5/6] Building and starting..."
ssh -i "$SSH_KEY" "$REMOTE_USER@$INSTANCE_IP" << REMOTE
cd $REMOTE_DIR
docker build -t job-agent .
docker stop job-agent 2>/dev/null || true
docker rm job-agent 2>/dev/null || true
docker run -d \
    --name job-agent \
    --restart unless-stopped \
    -p 7860:7860 \
    -v $REMOTE_DIR/backend/config.py:/app/backend/config.py \
    -v $REMOTE_DIR/data:/app/backend/data \
    job-agent
REMOTE

# 6. Add cron job to prevent Oracle from reclaiming idle instance
# Oracle reclaims instances with <20% CPU/network/memory over 7 days.
# This pings the app every 5 minutes to keep activity above threshold.
echo "[6/6] Setting up idle-prevention cron..."
ssh -i "$SSH_KEY" "$REMOTE_USER@$INSTANCE_IP" << REMOTE
(crontab -l 2>/dev/null | grep -v "job-agent.*idle-check"; echo "*/5 * * * * curl -sf http://localhost:7860/api/stats > /dev/null 2>&1 || docker restart job-agent") | crontab -
REMOTE

echo ""
echo "=== Deployed! ==="
echo "URL: http://$INSTANCE_IP:7860"
echo ""
echo "Next steps:"
echo "  1. SSH in: ssh -i $SSH_KEY $REMOTE_USER@$INSTANCE_IP"
echo "  2. Edit config: nano $REMOTE_DIR/backend/config.py"
echo "  3. Add your Groq API key and other secrets"
echo "  4. Restart: docker restart job-agent"

#!/bin/bash
# Quick redeploy to Vast.ai — syncs code only, restarts gunicorn.
# Data files are already on the server and don't need re-uploading.
#
# Usage: ./redeploy.sh
#
# Instance: RTX 5090 32GB  |  $0.2978/hr  |  id: 32638253
# SSH:      ssh -p 38252 -i ~/.ssh/id_ed25519 root@ssh9.vast.ai

set -e

echo "==> Fixing line endings..."
find . -maxdepth 1 \( -name "*.py" -o -name "*.sh" -o -name "*.html" \) \
  -not -path './.venv*' | xargs sed -i 's/\r//'

HOST="${AION_REMOTE_HOST:-root@ssh9.vast.ai}"
SSH_PORT="${AION_REMOTE_PORT:-38252}"
SSH_KEY="${AION_REMOTE_KEY:-$HOME/.ssh/id_ed25519}"
SSH="ssh -o StrictHostKeyChecking=no -p $SSH_PORT -i $SSH_KEY"

echo "==> Syncing code..."
rsync -az \
  -e "ssh -o StrictHostKeyChecking=no -p $SSH_PORT -i $SSH_KEY" \
  --exclude='data/' \
  --exclude='.venv*' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='hf_cache/' \
  --exclude='bin/' --exclude='lib/' --exclude='lib64' \
  --exclude='pyvenv.cfg' --exclude='*.mp3' \
  --exclude='cloudflared*' \
  --exclude='config_local.py' \
  --exclude='ui/node_modules/' \
  --exclude='deploy.sh' \
  /mnt/c/aion/ $HOST:/workspace/aion/

echo "==> Restarting Aion..."
# Note: use 'pkill gunicorn' (not -f) — pkill -f matches the SSH session cmdline and kills itself
$SSH $HOST 'cat > /tmp/start_aion.sh << SCRIPT
#!/bin/bash
pkill gunicorn || true
sleep 1
cd /workspace/aion
exec nohup gunicorn -w 1 -b 0.0.0.0:5000 --timeout 120 web:app >> /var/log/aion.log 2>&1
SCRIPT
chmod +x /tmp/start_aion.sh
setsid /tmp/start_aion.sh &
sleep 3
curl -s http://localhost:5000/ | grep -o "<title>[^<]*</title>"'

echo "==> Done."
echo "    SSH:    ssh -p $SSH_PORT -i $SSH_KEY $HOST"

#!/bin/bash
# Quick redeploy to Vast.ai — syncs code only, restarts gunicorn.
# Data files are already on the server and don't need re-uploading.
#
# Usage: ./redeploy.sh
#
# Instance: A100 SXM4 40GB  |  $0.468/hr  |  id: 32361950
# SSH:      ssh -p 11950 -i ~/.ssh/id_ed25519 root@ssh4.vast.ai
# Web:      https://drayhub.org

set -e
HOST="root@ssh4.vast.ai"
SSH_PORT="11950"
SSH_KEY="$HOME/.ssh/id_ed25519"
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
  --exclude='ui/node_modules/' \
  --exclude='deploy.sh' \
  /mnt/c/jarvis/ $HOST:/workspace/jarvis/

echo "==> Restarting Jarvis..."
# Note: use 'pkill gunicorn' (not -f) — pkill -f matches the SSH session cmdline and kills itself
$SSH $HOST 'cat > /tmp/start_jarvis.sh << SCRIPT
#!/bin/bash
pkill gunicorn || true
sleep 1
cd /workspace/jarvis
exec nohup gunicorn -w 1 -b 0.0.0.0:5000 --timeout 120 web:app >> /var/log/jarvis.log 2>&1
SCRIPT
chmod +x /tmp/start_jarvis.sh
setsid /tmp/start_jarvis.sh &
sleep 3
curl -s http://localhost:5000/ | grep -o "<title>[^<]*</title>"'

echo "==> Done."
echo "    Public: https://drayhub.org"

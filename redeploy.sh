#!/bin/bash
# Quick redeploy to Vast.ai — syncs code only, restarts gunicorn.
# Data files are already on the server and don't need re-uploading.
#
# Usage: ./redeploy.sh
#
# Instance: A100 SXM4 40GB  |  $0.468/hr  |  id: 32361950
# Web:      http://192.165.134.28:12557
# SSH:      ssh -p 12663 root@192.165.134.28

set -e
HOST="root@192.165.134.28"
SSH_PORT="12663"
SSH="ssh -o StrictHostKeyChecking=no -p $SSH_PORT"

echo "==> Syncing code..."
rsync -az \
  -e "ssh -o StrictHostKeyChecking=no -p $SSH_PORT" \
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
$SSH $HOST "pkill -f gunicorn || true; sleep 1; cd /workspace/jarvis && nohup gunicorn -w 1 -b 0.0.0.0:5000 --timeout 120 web:app > /var/log/jarvis.log 2>&1 &; sleep 3; curl -s http://localhost:5000/ | grep -o '<title>[^<]*</title>'"

echo "==> Done."
echo "    Local:  http://192.165.134.28:12557"
echo "    Public: https://drayhub.org"

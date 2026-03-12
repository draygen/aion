#!/usr/bin/env bash
set -euo pipefail

SSH_OPTS=(
  -o BatchMode=yes
  -o ConnectTimeout=20
  -o StrictHostKeyChecking=no
  -p 56821
  -i /home/draygen/.ssh/id_ed25519
)

ssh "${SSH_OPTS[@]}" root@183.89.209.74 <<'REMOTE'
set -euo pipefail
pkill -f 'gunicorn -w 1 -b 0.0.0.0:5000 --timeout 120 web:app' || true
cd /workspace/aion
gunicorn -w 1 -b 0.0.0.0:5000 --timeout 120 web:app --daemon
sleep 4
pgrep -af gunicorn
REMOTE

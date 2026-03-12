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
tmp="$(mktemp -d)"
cd "$tmp"

zap_url="$(curl -fsSL https://api.github.com/repos/zaproxy/zaproxy/releases/latest \
  | jq -r '.assets[] | select(.name | test("^ZAP_[0-9.]+_Linux\\.tar\\.gz$")) | .browser_download_url' \
  | head -n 1)"

test -n "$zap_url"
curl -fsSL "$zap_url" -o zap.tar.gz
tar -xzf zap.tar.gz -C /opt
zap_dir="$(find /opt -maxdepth 1 -type d -name 'ZAP_*' | sort | tail -n 1)"
test -n "$zap_dir"
test -f "$zap_dir/zap-baseline.py"

ln -sf "$zap_dir/zap-baseline.py" /usr/local/bin/zap-baseline.py
ln -sf "$zap_dir/zap.sh" /usr/local/bin/zap.sh
chmod +x "$zap_dir/zap-baseline.py" "$zap_dir/zap.sh"
ls -l /usr/local/bin/zap-baseline.py
head -n 1 "$zap_dir/zap-baseline.py"
REMOTE

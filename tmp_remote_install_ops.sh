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

httpx_url="$(curl -fsSL https://api.github.com/repos/projectdiscovery/httpx/releases/latest \
  | jq -r '.assets[] | select(.name | test("linux_amd64\\.zip$")) | .browser_download_url' \
  | head -n 1)"
ffuf_url="$(curl -fsSL https://api.github.com/repos/ffuf/ffuf/releases/latest \
  | jq -r '.assets[] | select(.name | test("linux_amd64\\.tar\\.gz$")) | .browser_download_url' \
  | head -n 1)"

test -n "$httpx_url"
test -n "$ffuf_url"

curl -fsSL "$httpx_url" -o httpx.zip
unzip -oq httpx.zip
install -m 0755 httpx /usr/local/bin/httpx

curl -fsSL "$ffuf_url" -o ffuf.tar.gz
tar -xzf ffuf.tar.gz
install -m 0755 ffuf /usr/local/bin/ffuf

/usr/local/bin/httpx -version
/usr/local/bin/ffuf -V | head -n 1
REMOTE

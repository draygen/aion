#!/usr/bin/env bash
set -euo pipefail

# Run this script directly on the host shell (not in restricted sandbox environments).

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo $0"
  exit 1
fi

cat >/etc/systemd/system/aion-web.service <<'EOF'
[Unit]
Description=Aion Flask Web Service (port 8888)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=draygen
WorkingDirectory=/mnt/c/aion
ExecStart=/mnt/c/aion/.venv/bin/python -c from\ web\ import\ app\;\ app.run\(host=\"127.0.0.1\",\
 port=8888,\ debug=False\)
Restart=always
RestartSec=3
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

cat >/etc/systemd/system/cloudflared-drayhub.service <<'EOF'
[Unit]
Description=Cloudflare Tunnel for drayhub.org
After=network-online.target aion-web.service
Wants=network-online.target

[Service]
Type=simple
User=draygen
WorkingDirectory=/mnt/c/projects/merge_syncforge
ExecStart=/mnt/c/aion/cloudflared --no-autoupdate --config /mnt/c/projects/merge_syncforge/cloudflared-config.yml tunnel run
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now aion-web.service
systemctl enable --now cloudflared-drayhub.service
systemctl restart aion-web.service cloudflared-drayhub.service

systemctl --no-pager --full status aion-web.service cloudflared-drayhub.service | sed -n '1,180p'

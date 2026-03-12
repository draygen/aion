#!/bin/bash
echo "Starting maintenance mode..."

# 1. Stop Aion processes
echo "Stopping Aion..."
pkill -f "python web.py" || true
pkill -f "gunicorn" || true
pkill -f "python drayops/run.py" || true

# 2. Stop JaredShare
echo "Stopping JaredShare..."
pkill -f "node server/index.js" || true
pkill -f "npm start" || true

# 3. Stop MFT Docker containers
echo "Stopping MFT Docker containers..."
docker stop mft-server-proxy-1 mft-server-server-1 mft-server-db-1 2>/dev/null || true

# 4. Kill ALL Cloudflare tunnels thoroughly
echo "Stopping ALL Cloudflare tunnels and services..."
echo "Renoise28!" | sudo -S systemctl stop cloudflared-drayhub 2>/dev/null || true
echo "Renoise28!" | sudo -S systemctl disable cloudflared-drayhub 2>/dev/null || true
echo "Renoise28!" | sudo -S systemctl stop cloudflared 2>/dev/null || true
echo "Renoise28!" | sudo -S systemctl disable cloudflared 2>/dev/null || true
echo "Renoise28!" | sudo -S pkill -9 -f "cloudflared" || true
pkill -9 -f "cloudflared" || true
sleep 3

# 5. Start Nginx for maintenance
echo "Starting Nginx maintenance server on port 8181..."
docker rm -f maint-nginx 2>/dev/null || true
docker run -d --name maint-nginx -p 8181:80 -v /mnt/c/aion/maintenance:/usr/share/nginx/html:ro nginx:alpine
sleep 2

# 6. Update Cloudflared configuration to point to maintenance page
echo "Reconfiguring cloudflared tunnel to route to Nginx at 127.0.0.1:8181..."
TUNNEL_ID="d08c0117-519b-423e-8318-8f9d1f23f80b"
CRED_FILE="/mnt/c/projects/merge_syncforge/d08c0117-519b-423e-8318-8f9d1f23f80b.json"

cat <<EOF > ~/.cloudflared/config.yml
tunnel: $TUNNEL_ID
credentials-file: $CRED_FILE
protocol: quic

ingress:
  - hostname: drayhub.org
    service: http://127.0.0.1:8181
  - hostname: www.drayhub.org
    service: http://127.0.0.1:8181
  - hostname: aion.drayhub.org
    service: http://127.0.0.1:8181
  - hostname: share.drayhub.org
    service: http://127.0.0.1:8181
  - hostname: sonchat.drayhub.org
    service: http://127.0.0.1:8181
  - hostname: syncforge.drayhub.org
    service: http://127.0.0.1:8181
  - service: http_status:404
EOF

# 7. Start Cloudflared tunnel for the maintenance page
echo "Starting Cloudflare tunnel (syncforge-nexus) for maintenance..."
nohup cloudflared tunnel --config ~/.cloudflared/config.yml run > /mnt/c/aion/maintenance/tunnel.log 2>&1 &

echo "=========================================="
echo "Maintenance mode is now ACTIVE."
echo "drayhub.org is pointing to the maintenance page."
echo "=========================================="
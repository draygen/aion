#!/bin/bash
echo "Stopping maintenance mode and starting services..."

# 1. Stop the maintenance Nginx server
echo "Stopping maintenance Nginx..."
docker stop maint-nginx 2>/dev/null || true
docker rm maint-nginx 2>/dev/null || true

# 2. Kill the maintenance Cloudflare tunnel
echo "Stopping maintenance Cloudflare tunnel..."
pkill -f "cloudflared" || true

# 3. Restore the original Cloudflared config
echo "Restoring Cloudflared configuration..."
if [ -f ~/.cloudflared/config.yml.bak ]; then
    mv ~/.cloudflared/config.yml.bak ~/.cloudflared/config.yml
fi

# 4. Start JaredShare (runs in background)
echo "Starting JaredShare..."
cd /mnt/c/projects/jaredshare
nohup ./start.sh > /mnt/c/projects/jaredshare/nohup.log 2>&1 &

# 5. Start Syncforge Tunnel Service
echo "Restarting Cloudflared System Service..."
echo "Renoise28!" | sudo -S systemctl enable cloudflared-drayhub 2>/dev/null || true
echo "Renoise28!" | sudo -S systemctl start cloudflared-drayhub 2>/dev/null || true

# 6. Start Aion
echo "Starting Aion..."
cd /mnt/c/aion
nohup ./start_web.sh > /mnt/c/aion/nohup.log 2>&1 &

# 6. Start MFT Docker containers
echo "Starting MFT Docker containers..."
docker start mft-server-db-1 mft-server-server-1 mft-server-proxy-1 2>/dev/null || true

echo "=========================================="
echo "Maintenance mode STOPPED."
echo "Services are starting in the background."
echo "Wait a moment for everything to initialize."
echo "=========================================="
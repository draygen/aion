#!/bin/bash
# Start Aion web server with Cloudflare Tunnel for public access

cd "$(dirname "$0")"

echo "Starting Aion web server..."

# Start Flask in background
python web.py &
FLASK_PID=$!

# Wait for Flask to start
sleep 2

# Check if Flask started successfully
if ! kill -0 $FLASK_PID 2>/dev/null; then
    echo "Error: Flask server failed to start"
    exit 1
fi

echo ""
echo "Starting Cloudflare Tunnel..."
echo "Your public URL will appear below (look for 'https://....trycloudflare.com')"
echo ""

# Run cloudflared (this will show the public URL)
./cloudflared tunnel --url http://localhost:5000

# When cloudflared exits, also stop Flask
kill $FLASK_PID 2>/dev/null

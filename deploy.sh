#!/bin/bash
# Aion deploy script — runs on the remote Vast.ai instance
set -e

echo "=== [1/6] System deps ==="
apt-get update -qq && apt-get install -y -qq curl python3-pip python3-venv rsync git

echo "=== [2/6] Install Ollama ==="
curl -fsSL https://ollama.com/install.sh | sh
ollama serve &>/var/log/ollama.log &
sleep 5

echo "=== [3/6] Pull qwen2.5:7b ==="
ollama pull qwen2.5:7b

echo "=== [4/6] Python deps ==="
pip3 install -q flask flask-cors scikit-learn gtts elevenlabs requests gunicorn beautifulsoup4

echo "=== [5/6] Start Aion ==="
cd /workspace/aion
mkdir -p data

# Start Flask via gunicorn on port 5000
pkill -f gunicorn || true
gunicorn -w 1 -b 0.0.0.0:5000 --timeout 120 --log-level info web:app \
  >> /var/log/aion.log 2>&1 &

echo "=== [6/6] Done — Aion running on :5000 ==="
echo "Ollama log: /var/log/ollama.log"
echo "Aion log: /var/log/aion.log"

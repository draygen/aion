#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/mnt/c/aion"
AION_CMD=("${ROOT_DIR}/.venv/bin/python" "-c" "from web import app; app.run(host='127.0.0.1', port=8888, debug=False)")
CLOUDFLARED_CMD=("${ROOT_DIR}/cloudflared" "--no-autoupdate" "--config" "/mnt/c/projects/merge_syncforge/cloudflared-config.yml" "tunnel" "run")

mkdir -p /tmp

start_pair() {
  "${AION_CMD[@]}" >>/tmp/aion-8888.log 2>&1 &
  AION_PID=$!

  "${CLOUDFLARED_CMD[@]}" >>/tmp/cloudflared-drayhub.log 2>&1 &
  CF_PID=$!
}

stop_pair() {
  kill "${AION_PID}" 2>/dev/null || true
  kill "${CF_PID}" 2>/dev/null || true
  wait "${AION_PID}" 2>/dev/null || true
  wait "${CF_PID}" 2>/dev/null || true
}

cleanup() {
  stop_pair
  exit 0
}

trap cleanup INT TERM

while true; do
  start_pair

  if ! wait -n "${AION_PID}" "${CF_PID}"; then
    :
  fi

  stop_pair
  sleep 3
done

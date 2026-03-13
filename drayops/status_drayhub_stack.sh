#!/usr/bin/env bash
set -euo pipefail

PID_FILE="/tmp/drayhub-stack.pid"

if [[ -f "${PID_FILE}" ]]; then
  PID="$(cat "${PID_FILE}" 2>/dev/null || true)"
  if [[ -n "${PID}" ]] && kill -0 "${PID}" 2>/dev/null; then
    echo "stack_runner=up pid=${PID}"
  else
    echo "stack_runner=down (stale pid file)"
  fi
else
  echo "stack_runner=down"
fi

if ps -ef | grep -F "/mnt/c/aion/.venv/bin/python -c from web import app; app.run(host='127.0.0.1', port=8888, debug=False)" | grep -v grep >/dev/null; then
  echo "aion_8888=up"
else
  echo "aion_8888=down"
fi

if ps -ef | grep -F "/mnt/c/aion/cloudflared --no-autoupdate --config /mnt/c/projects/merge_syncforge/cloudflared-config.yml tunnel run" | grep -v grep >/dev/null; then
  echo "cloudflared=up"
else
  echo "cloudflared=down"
fi

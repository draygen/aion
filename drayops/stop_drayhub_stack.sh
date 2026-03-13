#!/usr/bin/env bash
set -euo pipefail

PID_FILE="/tmp/drayhub-stack.pid"

if [[ ! -f "${PID_FILE}" ]]; then
  echo "drayhub stack is not running"
  exit 0
fi

PID="$(cat "${PID_FILE}" 2>/dev/null || true)"
if [[ -z "${PID}" ]]; then
  rm -f "${PID_FILE}"
  echo "drayhub stack pid file was empty; cleaned up"
  exit 0
fi

kill "${PID}" 2>/dev/null || true
sleep 1
kill -9 "${PID}" 2>/dev/null || true
rm -f "${PID_FILE}"
echo "stopped drayhub stack"

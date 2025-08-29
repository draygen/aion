#!/bin/bash

MODEL="mistral"
HOST="http://localhost:11434"
USER_INPUT="$1"

if [[ -z "$USER_INPUT" ]]; then
  echo "❌ No input detected."
  echo "Usage: ./run.sh \"What's up, Jarvis?\""
  exit 1
fi
curl -s -X POST "$HOST/api/chat" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "'"$MODEL"'",
    "messages": [
      {"role": "system", "content": "You are JARVIS, Brian Wallaces AI assistant. No fake dialogues or scenes. Just talk directly to him like a sarcastic, loyal companion. Respond with insight, personality, and honesty — not like a screenplay."},
      {"role": "user", "content": "'"$USER_INPUT"'"}
    ],
    "stream": true
  }' | jq -r '.message.content'

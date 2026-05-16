#!/bin/sh
set -e
PROMPT_FILE="/work/PROMPT.txt"
if [ ! -f "$PROMPT_FILE" ]; then
  echo "mc-entrypoint: $PROMPT_FILE not present" >&2
  exit 64
fi
PROMPT="$(cat "$PROMPT_FILE")"
if [ -n "$MULTICOOKER_MODEL" ]; then
  exec gemini --model "$MULTICOOKER_MODEL" --yolo --skip-trust -p "$PROMPT"
fi
exec gemini --yolo --skip-trust -p "$PROMPT"

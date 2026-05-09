#!/bin/sh
set -e
PROMPT_FILE="/work/PROMPT.txt"
if [ ! -f "$PROMPT_FILE" ]; then
  echo "mv-entrypoint: $PROMPT_FILE not present" >&2
  exit 64
fi
PROMPT="$(cat "$PROMPT_FILE")"
if [ -n "$MULTIVARKA_MODEL" ]; then
  exec gemini --model "$MULTIVARKA_MODEL" --yolo --skip-trust -p "$PROMPT"
fi
exec gemini --yolo --skip-trust -p "$PROMPT"

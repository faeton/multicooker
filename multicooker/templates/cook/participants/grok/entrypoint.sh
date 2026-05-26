#!/bin/sh
# grok (xAI CLI) entrypoint inside the multicooker sandbox.
# Reads /work/PROMPT.txt and prints the response. --always-approve auto-
# approves tool calls (container = sandbox). If MULTICOOKER_MODEL is set,
# pass it via -m so brief.yaml can pin grok-build / grok-build-latest.
set -e
PROMPT_FILE="/work/PROMPT.txt"
if [ ! -f "$PROMPT_FILE" ]; then
  echo "mc-entrypoint: $PROMPT_FILE not present" >&2
  exit 64
fi
PROMPT="$(cat "$PROMPT_FILE")"
if [ -n "$MULTICOOKER_MODEL" ]; then
  exec grok -p "$PROMPT" --always-approve -m "$MULTICOOKER_MODEL"
fi
exec grok -p "$PROMPT" --always-approve

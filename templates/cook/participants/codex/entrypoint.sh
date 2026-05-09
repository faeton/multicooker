#!/bin/sh
set -e
PROMPT_FILE="/work/PROMPT.txt"
if [ ! -f "$PROMPT_FILE" ]; then
  echo "mv-entrypoint: $PROMPT_FILE not present" >&2
  exit 64
fi
PROMPT="$(cat "$PROMPT_FILE")"
# If MULTIVARKA_MODEL is set, pin the model via -c model=<value>. codex
# accepts -c key=value to override config; the model key is the standard one.
if [ -n "$MULTIVARKA_MODEL" ]; then
  exec codex exec \
    --cd /work \
    --skip-git-repo-check \
    --dangerously-bypass-approvals-and-sandbox \
    -c "model=$MULTIVARKA_MODEL" \
    "$PROMPT"
fi
exec codex exec \
  --cd /work \
  --skip-git-repo-check \
  --dangerously-bypass-approvals-and-sandbox \
  "$PROMPT"

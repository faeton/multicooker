#!/bin/sh
set -e
PROMPT_FILE="/work/PROMPT.txt"
if [ ! -f "$PROMPT_FILE" ]; then
  echo "mv-entrypoint: $PROMPT_FILE not present" >&2
  exit 64
fi
PROMPT="$(cat "$PROMPT_FILE")"
exec codex exec \
  --cd /work \
  --skip-git-repo-check \
  --dangerously-bypass-approvals-and-sandbox \
  "$PROMPT"

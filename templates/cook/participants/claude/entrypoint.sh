#!/bin/sh
# claude entrypoint inside multivarka sandbox.
# Reads /work/PROMPT.txt, invokes the CLI with the canonical argv:
#   prompt BEFORE --add-dir (variadic --add-dir would otherwise eat it).
# Container = sandbox, so --dangerously-skip-permissions is the right flag.
# If MULTIVARKA_MODEL is set, pass --model so brief.yaml can pin the model
# (e.g. sonnet / opus / haiku / a specific id).
set -e
PROMPT_FILE="/work/PROMPT.txt"
if [ ! -f "$PROMPT_FILE" ]; then
  echo "mv-entrypoint: $PROMPT_FILE not present" >&2
  exit 64
fi
PROMPT="$(cat "$PROMPT_FILE")"
if [ -n "$MULTIVARKA_MODEL" ]; then
  exec claude --model "$MULTIVARKA_MODEL" --print --dangerously-skip-permissions "$PROMPT" --add-dir /work
fi
exec claude --print --dangerously-skip-permissions "$PROMPT" --add-dir /work

#!/bin/sh
# agy (Google Antigravity CLI) entrypoint inside the multicooker sandbox.
# Reads /work/PROMPT.txt and runs a single non-interactive prompt.
# Container = sandbox, so --dangerously-skip-permissions is the right flag.
# agy's --print-timeout defaults to 5m; raise it (default 1h, overridable via
# MULTICOOKER_PRINT_TIMEOUT) so long tool loops aren't cut off before the
# participant timeout_s does. If MULTICOOKER_MODEL is set, pass --model so
# brief.yaml can pin a model (see `agy models` for valid names).
set -e
PROMPT_FILE="/work/PROMPT.txt"
if [ ! -f "$PROMPT_FILE" ]; then
  echo "mc-entrypoint: $PROMPT_FILE not present" >&2
  exit 64
fi
PROMPT="$(cat "$PROMPT_FILE")"
PRINT_TIMEOUT="${MULTICOOKER_PRINT_TIMEOUT:-3600s}"
if [ -n "$MULTICOOKER_MODEL" ]; then
  exec agy --model "$MULTICOOKER_MODEL" --print "$PROMPT" \
       --print-timeout "$PRINT_TIMEOUT" --dangerously-skip-permissions --add-dir /work
fi
exec agy --print "$PROMPT" \
     --print-timeout "$PRINT_TIMEOUT" --dangerously-skip-permissions --add-dir /work

#!/bin/sh
# Dummy participant/judge for integration smoke tests.
#
# Two modes, switched by env:
#   - MULTICOOKER_JUDGE set → judge: scan /work/submissions/<letter>/, emit
#     fixed scores per submission to /work/outbox/scores.json + review.md.
#   - else → participant: copy /work/PROMPT.txt to /work/out/RESULT.md.
#
# Both modes are deterministic, exit 0 quickly, and need zero network or
# credentials. Anything fancier defeats the purpose — for real LLM
# behavior use claude/codex/gemini.
set -e

if [ -n "$MULTICOOKER_JUDGE" ]; then
    mkdir -p /work/outbox
    {
        printf '{\n'
        first=1
        for d in /work/submissions/*/; do
            [ -d "$d" ] || continue
            letter=$(basename "$d")
            if [ "$first" -eq 0 ]; then printf ',\n'; fi
            first=0
            # Fixed score: 3/5 across the board if RESULT.md exists, else 0.
            if [ -f "$d/out/RESULT.md" ]; then
                printf '  "%s": {"dimensions": {"correctness": 3, "quality": 3, "honesty": 3, "completeness": 3}, "total": 60.0}' "$letter"
            else
                printf '  "%s": {"dimensions": {"correctness": 0, "quality": 0, "honesty": 0, "completeness": 0}, "total": 0.0}' "$letter"
            fi
        done
        printf '\n}\n'
    } > /work/outbox/scores.json
    echo "dummy judge: scored $(ls -d /work/submissions/*/ 2>/dev/null | wc -l | tr -d ' ') submission(s)." > /work/outbox/review.md
    exit 0
fi

# Participant mode.
PROMPT_FILE="/work/PROMPT.txt"
if [ ! -f "$PROMPT_FILE" ]; then
    echo "mc-entrypoint: $PROMPT_FILE not present" >&2
    exit 64
fi
mkdir -p /work/out
cp "$PROMPT_FILE" /work/out/RESULT.md

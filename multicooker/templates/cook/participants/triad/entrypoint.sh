#!/bin/sh
# triad entrypoint — Claude is the LEAD ENGINEER; Codex and Grok are in-cell
# reviewers it consults via Bash. All three CLIs are installed in mc-base-triad
# and authenticated by the cred mounts (compose_render._auth_volumes). Claude
# drives the build/review/integrate loop itself — we just hand it the task plus
# a review protocol so it knows the reviewers exist and how to call them.
#
# Canonical claude argv quirk: the prompt MUST come before --add-dir, else the
# variadic flag eats the positional. Container = sandbox, so the bypass flags
# (claude --dangerously-skip-permissions, codex --dangerously-bypass-..., grok
# --always-approve) are the correct setting.
set -e

PROMPT_FILE="/work/PROMPT.txt"
[ -f "$PROMPT_FILE" ] || { echo "mc-entrypoint(triad): $PROMPT_FILE not present" >&2; exit 64; }
mkdir -p /work/out

# Judge mode (MULTICOOKER_JUDGE): score plainly as Claude, no review panel.
if [ -n "$MULTICOOKER_JUDGE" ]; then
  if [ -n "$MULTICOOKER_MODEL" ]; then
    exec claude --model "$MULTICOOKER_MODEL" --print --dangerously-skip-permissions "$(cat "$PROMPT_FILE")" --add-dir /work
  fi
  exec claude --print --dangerously-skip-permissions "$(cat "$PROMPT_FILE")" --add-dir /work
fi

REVIEW_PROTOCOL='# Multi-model review protocol — you are the LEAD ENGINEER

Two INDEPENDENT reviewer CLIs are preinstalled and authenticated in this
sandbox. They are your review panel. After each solid piece of engineering (a
screen, a system, a non-trivial refactor), send the relevant files to BOTH and
integrate what holds up:

  # Codex (OpenAI) — correctness / bug / spec-fidelity review
  codex exec --cd /work --skip-git-repo-check \
        --dangerously-bypass-approvals-and-sandbox \
        "Review the changes I just made under /work/out for bugs, correctness,
         and fidelity to /work/BRIEF.md. Be specific and terse."

  # Grok (xAI) — independent second opinion: edge cases + craft
  grok -p --always-approve \
       "Independently review /work/out against /work/BRIEF.md: bugs, edge cases,
        and visual/interaction craft. What would you change and why?"

Rules:
- Consult BOTH at least once per milestone. Weigh their critiques; keep what is
  correct, discard what is wrong. You are the lead, not a vote-counter.
- Never let a reviewer block you: if a call errors or times out, proceed.
- They review; they do not write. YOU author every file under /work/out.
- In RESULT.md add a short "Review panel" note: what Codex and Grok each caught,
  and what you accepted vs. rejected. Be honest — this is graded on honesty.

Now do the task below.

============================================================
'

FULL="${REVIEW_PROTOCOL}$(cat "$PROMPT_FILE")"

if [ -n "$MULTICOOKER_MODEL" ]; then
  exec claude --model "$MULTICOOKER_MODEL" --print --dangerously-skip-permissions "$FULL" --add-dir /work
fi
exec claude --print --dangerously-skip-permissions "$FULL" --add-dir /work

# multicooker — notes for agents

multicooker runs several LLM agents (`claude` / `codex` / `agy`
/ `grok`) on **the same task** in parallel docker containers using
their own subscription auth, then has **other** LLMs read the
outputs blind and score them by a rubric you define. Output: a
leaderboard plus a corpus of N divergent solutions to one
underspecified brief.

## Hard rules

1. **Everything in docker.** Containers are the sandbox; that's
   why participant CLIs run with their respective dangerous
   approval-bypass flags. They can't reach the host. Runtime
   details — `docs/orchestration.md`.
2. **No API keys.** Subscription creds (`Claude Pro` /
   `ChatGPT Plus` / `Gemini Advanced` / `SuperGrok`) are
   bind-mounted or in named volumes, RO. See `docs/auth.md`.
3. **One cook = one folder `cooks/<YYMMDD-name>/`.** Created via
   `multicooker new <name>`. Date prefix is added automatically;
   if the user already provided a `YYMMDD-` prefix, it isn't
   duplicated. Subsequent commands take the full prefixed name.
4. **Never edit other cooks.** Write artifacts only inside the
   cook you were asked to make.

## When asked to "scaffold a cook for X"

**Always start by copying the closest example as a structural
template** — don't write a cook from scratch:

- `examples/hello-task/` — minimal text task on `dummy` flavor (no
  LLM creds). Use as the shape when the user wants short-text or
  smoke-test output.
- `examples/design-landing/` — real aesthetic task with a
  5-dimension visual rubric and cross-flavor judges. Use as the
  shape for design / copy / open creative tasks.

Then:

```bash
multicooker new <name> --participants <list>   # → cooks/<YYMMDD-name>/
```

`<list>` is comma-separated. Either `flavor` shorthand
(`claude,codex,agy,grok` → participants named after their
flavor) or explicit (`alice=claude,bob=claude,codex,agy`).
Per-participant model selection goes into `brief.yaml` (see below).

Then fill in four pieces inside the new cook.

### `BRIEF.md` — what participants must do

Canonical sections, in order:

```markdown
# Task: <one-line title>

## Goal              — what the user is actually trying to do
## Inputs            — what's in ./raw/ (RO), what each file is for
## Output            — exactly what must be in ./out/, by file path
## Constraints       — hard requirements (format, no build, max size)
## Anti-goals        — what to NOT do (copy-paste, fake metrics, etc.)
## Success criteria  — the rubric dimensions, id + one-line meaning
```

Ambiguity in **Goal** is fine — that's where participants diverge,
which is the point. Ambiguity in **Success criteria** is not — the
judge will improvise and scores become noisy.

### `brief.yaml` — who, timeouts, rubric

```yaml
name: <task>                  # short slug, matches folder suffix
timeout_s: 600                # per participant; design tasks need room
judge_timeout_s: 300

participants:
  - { name: claude, flavor: claude }
  - { name: codex,  flavor: codex }
  - { name: agy, flavor: agy, model: "Gemini 3.1 Pro (High)" }   # model is optional; see `agy models`

judges:
  - { name: judge-claude, flavor: claude }   # see anti-self-judge below
  - { name: judge-codex,  flavor: codex }

rubric:
  scale: [0, 5]               # per-dimension score range
  dimensions:
    - { id: correctness,  weight: 40 }       # weights are relative,
    - { id: quality,      weight: 30 }       # don't have to sum to 100
    - { id: completeness, weight: 30 }
```

### `JUDGE_BRIEF.md` — how judges score

Mirror the rubric: same dimension `id`s, same order, plus a short
"what you're scoring" line per dimension. Tell the judge:

- it sees anonymized submissions under `A` / `B` / `C` / … (never
  flavor names);
- it must write `./outbox/scores.json` (strict JSON,
  `scores[label][dim]: int`) and `./outbox/review.md` (one
  paragraph per submission, concrete quotes, no flavor names);
- it must score every submission even if it's empty (give 0s and
  say so in the review).

### Anti-self-judge — choosing judges

Whether a judge scores submissions from its **own flavor** (claude
judging claude's output) is a **policy**, not an automatic guarantee.
Set it in `brief.yaml`:

```yaml
judging:
  policy: require_distinct_flavor   # | warn | allow_self
```

- `require_distinct_flavor` — drops every same-flavor (judge,
  submission) score before aggregation; this is the real blind-judge
  guarantee. Use it for unattended / control-plane runs.
- `warn` — **the default**: same-flavor scores are *kept*, only an
  advisory is printed. So absent explicit policy, claude *can* score
  claude.
- `allow_self` — keep them, no warning.

When designing judge lineups, still aim for cross-flavor coverage so
strict mode doesn't leave a submission scored by no one:

- For every participant flavor, at least **one judge of a
  different flavor** must exist, otherwise that submission is
  scored by no one (under `require_distinct_flavor`).
- With one participant flavor, you cannot judge it with that
  flavor's judge — pick a different judge flavor.
- With several participant flavors (e.g. claude/codex/agy/grok),
  two judges of different flavors is typically enough: every
  submission ends up scored by at least one non-self judge
  (submissions of the judge flavors get scored by the other judge;
  the remaining flavors get scored by both). Add a third judge if
  you want symmetric two-judge coverage on every submission.

### `raw/` — references

`cp` whatever the user pointed to into `cooks/<name>/raw/` and
reference files by relative path from `BRIEF.md` (`./raw/<file>`).
The whole directory is mounted RO into every participant container.

### Run

```bash
multicooker cook   <name>     # all participants in parallel
multicooker judge  <name>     # anonymized scoring
multicooker report <name>     # → cooks/<name>/leaderboard.md
```

## Iteration

- `multicooker refine <name>` — round N+1 atop previous `out/`.
  Reads `cooks/<name>/FEEDBACK.md` (common) and
  `FEEDBACK_<participant>.md` (per-participant, optional).
- `multicooker rejudge <name>` — re-run judging only; useful after
  editing `JUDGE_BRIEF.md` or hand-fixing `out/`.
- `multicooker diff <name>` — file-level diff between two refine
  rounds; sanity check that refine moved the needle.

## What participant containers see (you rarely need to touch this)

- Each participant: own container on own bridge network. Sees
  `/work/BRIEF.md` (RO), `/work/raw/` (RO), `/work/out/` (RW), own
  creds. **Doesn't see**: other participants, `judging/`, the
  `A↔flavor` mapping, the rest of the repo.
- Each judge: own container on own bridge network. Receives
  **copies** (not symlinks) of brief, judge brief, raw, and the
  anonymized `submissions/{A,B,C}/`. The `A↔flavor` mapping lives
  only on the host.
- Egress is open: participants legitimately reach
  npm/pypi/github/docs while solving the task. The sandbox is the
  container, not the network.

If a cook needs custom tools (`tshark`, `pandas`, a Go compiler),
add them to the Dockerfile of **this cook**, not the template.
Cooks are independent.

## Further reading

- `README.md` — user-facing TL;DR.
- `HOWTO.md` — long-form mechanics and lessons learned.
- `docs/setup-new-cook.md` — step-by-step new-cook walkthrough.
- `docs/orchestration.md` — compose layout, networks, mounts,
  permission flags, per-flavor argv.
- `docs/auth.md` — subscription auth in containers.
- `docs/pitfalls.md` — gotchas inherited from `reproxy/arena`.
- `docs/implementation-status.md` — what works, what's deferred.

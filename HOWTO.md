# multicooker — HOWTO (the long version)

Detailed description of how multicooker works, what it does, why it
does it this way, and which rules you can't break. If you just want
to run it — see [README.md](README.md). This file is for
understanding the internals and for extending it.

## Contents

1. [Why this exists at all](#why-this-exists-at-all)
2. [Mental model](#mental-model)
3. [`cook` folder structure](#cook-folder-structure)
4. [What happens in `multicooker cook`](#what-happens-in-multicooker-cook)
5. [What happens in `multicooker judge`](#what-happens-in-multicooker-judge)
6. [Rules (which are easy to break)](#rules-which-are-easy-to-break)
7. [Docker-mode (the only one)](#docker-mode-the-only-one)
8. [Auth and cost](#auth-and-cost)
9. [What to do when something breaks](#what-to-do-when-something-breaks)
10. [Extensions and next steps](#extensions-and-next-steps)
11. [Lessons from reproxy/arena](#lessons-from-reproxyarena)

---

## Why this exists at all

Sometimes a task is so underspecified that there's no single
"correct" solution. You want to see how different LLMs interpret it
and what comes out — not so much to "declare a winner" as to get a
**corpus of 3+ diverging solutions** to the same task. This gives
you:

- ideas you wouldn't have come up with yourself;
- understanding of where LLMs agree and where they diverge
  (divergences usually highlight where the task is underspecified);
- an honest, beyond-marketing sanity-check of which model handles
  your particular kind of task better.

The ancestor is `reproxy/arena/` (now on branch `archive/arena`),
which ran claude/codex/gemini in a three-round tournament over
network scenarios and from which the v0.1.0 release was assembled.
Lessons squeezed out of that experience are described at the end.

## Mental model

```
                          one task
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
         ┌────────┐      ┌────────┐      ┌────────┐
         │ claude │      │ codex  │      │ gemini │      ← parallel, isolated
         │ /work/ │      │ /work/ │      │ /work/ │
         └───┬────┘      └───┬────┘      └───┬────┘
             │ raw/ (read-only, shared)      │
             └────────────┬───────────────────┘
                          ▼
                   sealed snapshots
                          │
              ┌───────────┴────────────┐
              ▼                        ▼
         ┌────────┐              ┌────────┐
         │ judge  │              │ judge  │           ← scoring panel
         │ claude │              │ gemini │             (anonymized A/B/C)
         └───┬────┘              └───┬────┘
             │                       │
             └─────────┬─────────────┘
                       ▼
                 leaderboard.md
```

Key properties:

1. **Parallelism.** All participants run at the same time (threads
   on the host, or containers in docker-mode). Nobody waits for
   anyone.
2. **Isolation.** Each one sees only its own `work/<name>/` plus a
   shared `raw/` (read-only). They don't see each other.
3. **Judge anonymization.** Participants reach the judge as `A`,
   `B`, `C`, ... — it doesn't know which model wrote what. The
   mapping is recovered only in the final report.
4. **Anti-self-judge.** If the judge is the same flavor as one of
   the participants, multicooker prints a WARN (but still judges).
   Anonymization already strips some of the bias; for hard isolation
   add a judge of a third flavor (e.g. another codex-judge) that
   isn't among the participants.

## `cook` folder structure

After `multicooker new my-task`:

```
cooks/my-task/
├── BRIEF.md             # you write the task for participants here
├── brief.yaml           # participants, timeouts, rubric
├── JUDGE_BRIEF.md       # judge instructions + rubric
├── raw/                 # you drop reference materials here
│   └── .gitkeep
└── work/                # participant work folders (created empty)
    ├── claude/
    ├── codex/
    └── gemini/
```

After `multicooker cook my-task` the following are added:

```
cooks/my-task/
├── RUN.json                          # run metadata
├── RUN_RESULT.json                   # participant statuses
├── work/<p>/BRIEF.md                 # symlink to ../../BRIEF.md
├── work/<p>/raw/                     # symlink to ../../raw
├── work/<p>/out/                     # participant writes its result here
├── logs/<p>/<flavor>.stdout.log      # raw CLI stdout
└── logs/<p>/<flavor>.stderr.log      # raw CLI stderr
```

After `multicooker judge my-task`:

```
cooks/my-task/judging/
├── _inbox/<p>/                       # frozen copy of work/<p>/
├── _judge_input/                     # anonymized input for the judges
│   └── submissions/{A,B,C}/
├── _logs/<judge-name>/               # judge CLI logs
├── _mapping.json                     # A→claude, B→codex, ...
├── <judge-name>/scores.json          # raw scores (by A/B/C)
├── <judge-name>/scores_deanon.json   # with names revealed
└── <judge-name>/review.md            # textual justification
```

After `multicooker report my-task`:

```
cooks/my-task/leaderboard.md
```

## What happens in `multicooker cook`

Pseudocode:

```python
for participant in brief.participants:
    setup work/<participant>/                 # folder + symlink BRIEF.md + symlink raw/
    spawn thread:
        run host CLI(<flavor>) in work/<participant>/ with prompt = brief
        capture stdout/stderr to logs/<participant>/
        on rate-limit: record evidence, return (don't sleep — others are working)
        on success/timeout: copy work/<participant>/ → judging/_inbox/<participant>/
join all threads
write RUN_RESULT.json
```

Specific technical nuances:

### Startup stagger
A 2-second pause between launching participants. Otherwise all
three CLIs hit auth-refresh at the same time, and the Keychain
under load can return an error.

### Rate-limit handling
Each CLI has its own "you hit the limit" patterns (see
`multicooker/runner_common.py:_RL_PATTERNS`). If they appear in the
tail of stdout/stderr — the participant is marked `rate_limited`
with a pointer to the specific evidence line. **We don't block the
others** — claude and gemini have independent limits, codex may
die, claude and gemini will finish normally.

### macOS sleep detection
On a Mac `caffeinate -dimsu -w <pid>` prevents the system from
sleeping while the CLI is running. But if the laptop is on a closed
lid — caffeinate doesn't help. Then we compare `time.time()` (wall)
and `time.monotonic()` (which pauses during sleep on macOS), and
if the difference is > 60s — we assume the laptop slept, and retry
once (API connections almost certainly dropped).

### Argv ordering
One of the arena bugs: the claude CLI has a variadic `--add-dir`,
which swallows the positional prompt as another path. So the
**prompt goes BEFORE `--add-dir`**:

```bash
claude --print "<prompt>" --add-dir /work
```

and not

```bash
claude --add-dir /work --print "<prompt>"   # ←  prompt gets lost
```

This is baked into
`templates/cook/participants/claude/entrypoint.sh` — for the
canonical argv order per flavor see `docs/orchestration.md`.

### Output "contract"
The participant must put its result under `./out/`. This is a
convention spelled out in the template prompt. The judge looks
there too. If a participant ignored it and dumped files at the
root — the judge will see them anyway (it sees the whole worktree
except symlinks).

## What happens in `multicooker judge`

```python
participants = brief.participants
mapping = {A: claude, B: codex, C: gemini} (random shuffle)
copy each work/<participant>/ → _judge_input/submissions/<letter>/
for judge in brief.judges:
    warn if judge.flavor == any participant.flavor   # anti-self-judge (advisory only)
    copy JUDGE_BRIEF.md + raw/ + submissions/ into a fresh _work-<judge>-XXX/
    run host CLI(<judge.flavor>) in that work-dir
    expect ./outbox/scores.json + ./outbox/review.md
    deanonymize scores using mapping
    write deanon to judging/<judge-name>/scores_deanon.json
```

### Why symlinks in the judge work-dir are forbidden
Arena bug #1: the judge received `./inbox` and `./outbox` as
symlinks to the real folders. CLI sandboxes (`claude --add-dir
<work>`) allow reads/writes only inside their own work-dir. A
symlink pointing outside resolves to a path that isn't in the
allowlist, and Read/Bash/Write **silently** refuse. The result:
97% of scores were placeholders.

The fix: **no symlinks**. JUDGE_BRIEF.md, raw/, submissions/ are
**copied** into the judge's work-dir (not symlinked). After the
run the contents of `work/outbox/` are copied back into
`judging/<judge-name>/`.

### Why anonymization matters
If the judge sees "submission claude/" — the claude-judge will tend
to score "its own" higher (or the opposite, lowballing to
compensate). Anonymization plus the anti-self-judge rule remove the
crudest sources of bias.

Be aware: **bias is not fully removed**. claude vs gemini code
style is recognizable. If you want more — add a third judge (any
anti-bias measure benefits from larger N), and/or ask an agent
wrapper to paraphrase outputs before judging (not implemented in
v0.1, on the TODO list).

## Rules (which are easy to break)

1. **Don't let the judge read the participant's stderr.log.** In
   stderr the CLI often puts something like "Claude is thinking..."
   — instant deanon. We put **only the participant's work-tree**
   into judging/_inbox/, without logs/.

2. **JUDGE_BRIEF.md and BRIEF.md must share the same rubric.** If
   you add a dimension to BRIEF.md and forget JUDGE_BRIEF.md, the
   judge will score something other than what was promised in the
   brief.

3. **Don't edit work/<p>/ after cook.** If you want to "help" a
   participant — that's not its result anymore. If you want to give
   everyone a hint — update BRIEF.md or raw/ and cook again.

4. **raw/ — read-only by convention.** Technically the filesystem
   lets the participant write there (we use a symlink). Don't trust
   it: if the task is sensitive, after cook do
   `diff -r raw/ <expected>/` and confirm the participant didn't
   change it. Or chmod 555 raw/ before cook.

5. **API limits are unpredictable.** Don't run an overnight cook
   without `RUN_RESULT.json` post-processing. In the morning check:
   were any participants `rate_limited`? If yes, and they matter to
   you — plan a re-run (not implemented in v0.1: run manually after
   quota recovery).

## Docker-mode (the only one)

Starting from v0.2 multicooker only runs in docker-mode. Host-mode
and `host_runner.py` have been removed — if something broke without
them, fix it in docker-mode.

- Each participant and each judge — its own container on its own
  bridge network (`net-participant-<name>` / `net-judge-<name>`).
  No inter-container DNS/IP visibility within a cook.
- Egress to the internet is open. The sandbox is the container,
  not the network. If a particular cook needs a strict allowlist —
  drop in a local `compose.override.yaml`.
- Subscription credentials (Claude Pro / ChatGPT Plus / Gemini
  Advanced) are snapshotted into `cooks/<task>/.auth/<flavor>/`
  (mode `0600`, `.gitignore`) and bind-mounted RO into the
  corresponding container. **API keys are not needed**, and there
  is no silent fallback to an API key. See `docs/auth.md`.
- Permission-bypass flags (`--dangerously-skip-permissions`,
  `--yolo`, `--dangerously-bypass-approvals-and-sandbox`) are
  mandatory inside the container: without them the CLIs hang on
  approval prompts. Safe, because the container contains them.
- Shared base images (`mc-base-<flavor>:latest`) install the heavy
  stuff (`npm i -g <cli>`), and the cook Dockerfile is shortened
  to `FROM mc-base-<flavor>` + entrypoint. Cook image build is
  ~1 sec instead of 2-3 min. `multicooker build-base` builds them
  manually; cook / refine / judge call `base_images.ensure_built()`
  themselves, so it's transparent to the user.

Threat model and what exactly the container protects: see
[`docs/security.md`](docs/security.md).

## Auth and cost

### Subscriptions
- Subscription-only auth: Claude Pro $20/mo, ChatGPT Plus $20/mo,
  Gemini Advanced $20/mo. Enough for several tasks a day; limits
  are low — a typical cook with 3 participants burns ≈ 30k–200k
  tokens per participant.
- API keys are not used and **not wired in as a fallback**: if a
  subscription cred is unavailable, `multicooker doctor` / `cook`
  fail loudly with a remediation message, rather than silently
  falling back to a paid API.

### Cook budget
Rough estimate:

```
participants × tokens_per_participant × $/token
+ judges × tokens_per_judge × $/token
```

For a typical "write a 2-page essay" task: ~$0.30–$1.50. For
"rewrite this repository": ~$5–$30 (depends on size).

v0.1 has no cost-tracker. If you need one — look at
prompt+completion in the subscription CLI logs or in the API
ledger. v0.2 wants an automatic ledger (one of the TODOs).

## What to do when something breaks

### "claude CLI not in PATH"
```
brew install claude-code     # or the official anthropic installer
```
Same for `codex` and `gemini`. If you don't need a particular
participant — remove it from `brief.yaml` before cook.

### "the judge didn't write scores.json"
Look at `cooks/<name>/judging/_logs/<judge>/<flavor>.stdout.log`.
Most common cases:
- the judge hit its own rate-limit;
- the judge considered the task too ambiguous and asked for
  clarification (visible in its output);
- the judge tripped over the symlink bug (shouldn't happen with
  this version of the judge — we copy, we don't symlink).

### "scores look random"
Most often the rubric is unclear to the judge. Re-read your
`JUDGE_BRIEF.md` with the eyes of a disinterested person. If a
dimension says "quality" without a definition — the judge scores
at random. The more concrete the phrasing ("did the answer
reference all 3 source documents?"), the more stable the scores.

### "claude ate all the CPU"
Each CLI is multi-threaded on its own. Three parallel claudes can
saturate a laptop. Lower parallelism:
```yaml
participants:
  - name: claude
    flavor: claude
  # codex and gemini commented out; run in two passes
```
v0.2 wants a `--max-parallel N` flag.

## Refine: round N+1 on top of the previous result

Not every task gets solved in one round. `multicooker refine
<task>` runs another round on top of the previous output:

- Each participant sees its previous `./out/` **in place, RW** —
  edits/replaces/extends it.
- Before the run, the previous round is snapshotted into
  `rounds/<N>/<p>/` (immutable history), plus the sealed
  `judging/_inbox/` is copied into `rounds/<N>/_inbox/`.
- Inlined into `PROMPT.txt` are:
  - **shared feedback** from `cooks/<task>/FEEDBACK.md` (a common
    review for everyone);
  - **personal feedback** from `cooks/<task>/FEEDBACK_<flavor>.md`
    (optional, addressed to a specific participant).
- `--participants <list>` lets you refine a subset.
- `--feedback <path>` swaps the source of shared feedback for an
  arbitrary file — handy when one piece of feedback applies to
  several cooks.
- `multicooker diff <task> N M` shows a unified diff between
  rounds per participant — a sanity-check that refine actually
  changed something.

Round artifacts: `REFINE_<N>.json` (start metadata),
`REFINE_<N>_RESULT.json` (status + duration + rate-limit info per
participant). The full artifact lifecycle is in
[`docs/lifecycle.md`](docs/lifecycle.md).

After refine, the same judging step is expected:
`multicooker judge <task>` → `multicooker report <task>`.

### `multicooker rejudge <task>`

A separate command: re-judge **the same** snapshot without a
re-cook. Useful when you've edited `JUDGE_BRIEF.md` (rubric,
weights) or manually patched `out/<p>/RESULT.md`. It does three
things:

1. Re-seals `judging/_inbox/<p>/` from the current `work/<p>/out/`
   (important — a regular `judge` uses the already-sealed inbox
   and will miss edits to `out/`).
2. Cleans previous judges' outboxes in `judging/<judge>/`.
3. Calls the regular `judge` flow (fresh anonymization —
   `_mapping.json` is always regenerated, the anti-bias guarantee
   is not weakened).

Parameters: `--judges` (same as `judge`).

Each participant run also writes `work/<p>/trace.json` with
`{prompt, model, exit_code, duration_s, started_at, status}` — a
cheap structured artifact for debugging and for future replay
scenarios. A full structured-trace version (tool calls) is
deferred — see `docs/design-notes.md`.

## Extensions and next steps

What's left on the TODO list (see `docs/todo.md` for the current
list):

1. **Cost ledger** — on every run, parse usage from the CLI and
   write `cook/cost_ledger.json`.
2. **Resume** — `multicooker resume <name>` re-runs only
   `rate_limited` or `error` participants, leaving `ok` alone.
3. **Per-participant timeout** (currently a global `timeout_s`).
4. **`multicooker diff <task> N M`** — round comparison.
5. **Replayable traces / registry** — structured run trace,
   versioned task specs (ideas from agentevals / OpenAI Evals).
6. **Web report** — `multicooker serve <name>` shows HTML with
   diffs between submissions, judging logs, and the leaderboard.
7. **Cross-cook leaderboard** — global table "claude wins 7 out
   of 10 tasks, codex 2, gemini 1".

## Lessons from reproxy/arena

What overnight runs taught us not to do:

- **Variadic CLI flags ALWAYS swallow positional args.** `claude`
  with `--add-dir <wt>` after the prompt leaves the prompt hanging
  on stdin → 0-byte diff → "0/100 on correctness". Fix: prompt
  BEFORE variadic flags.
- **Symlinks inside the sandbox allowlist.** Don't work. The CLI
  sees a path that resolves outward, silently refuses, no errors —
  just an empty outbox. Fix: never symlink into a work-dir we hand
  to the CLI with `--add-dir`. Only copy.
- **Codex quota overruns.** OpenAI ChatGPT Plus quota ran out
  every ~5 hours mid-round → one of the three "zeroed out". Fix:
  accept it (can't be worked around) and in the orchestrator do a
  per-participant deferred-retry so the others aren't blocked.
- **Don't trust the exit code.** Many CLIs return 0 even when they
  hit a limit, because they "successfully reported the limit".
  Fix: always parse stderr for known-bad patterns.
- **Don't write markdown handovers for the CLI expecting it to
  read them.** It will read. But it won't act on it. If you want
  the participant to change behavior — put it in the **prompt**,
  not in a file.
- **Mid-run sleep on a Mac.** Connection drops to the Anthropic
  API ← closed lid. caffeinate doesn't always help. Fix —
  retroactive detection via wall-vs-monotonic skew + one retry.
- **Don't trust the leaderboard from the first run.** Reproxy-arena
  overnight #1 showed gemini > codex > claude. After fixing the
  argv bug and the judge symlinks, the order changed. Only after a
  smoke test and a second run were the numbers meaningful.
- **Artifacts eat disk fast.** Reproxy-arena: 4.3 GB over two
  overnights. In multicooker the artifact = only `cook/<name>/`,
  no round snapshots; the cap is low, but the habit of cleaning up
  old cooks is useful.

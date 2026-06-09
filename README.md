# multicooker

Run several LLM agents (`claude`, `codex`, `agy`, `grok`) on
**the same task** in parallel — each in its own docker container
with its own subscription auth — then have **other** LLM agents
read the outputs blind (under `A` / `B` / `C` labels), score them
against your rubric, and write reviews.

You get a `leaderboard.md` plus a corpus of N divergent solutions
to one brief. **No API bills**: it goes through your `Claude Pro`
/ `ChatGPT Plus` / `Gemini Advanced` / `SuperGrok` subscriptions.

There's also a composite **`triad`** flavor — Claude as the lead
engineer with Codex and Grok in the *same* container as in-cell
reviewers it consults itself (build → review → integrate, multi-model
review *inside* one build). Good as the chef/lead, not a blind
competitor. See [`docs/add-flavor.md`](docs/add-flavor.md#composite-flavors-triad).

> «multicooker»: one task, several dishes cook in parallel in
> their own pots; you compare what came out of each.

> 🇷🇺 Russian version: [`README.ru.md`](README.ru.md).

## Why

When a task is underspecified — design, copy, refactoring with
architectural choice, code review — there is no single "correct"
answer. Any model will fill in the gaps from the brief itself, and
**what** it fills in is the interesting part. A single run through
a single model doesn't show this; you only see one interpretation
and assume it's "the answer".

multicooker gives you a **corpus of divergent interpretations** of
the same brief in one shot. Useful when:

- You're picking between models for a recurring task (refactoring,
  design, doc writing, code review) and tired of deciding by vibes.
- You want to see where a brief is underspecified — disagreement
  between models highlights exactly those spots.
- You're doing design or copy work and want three takes from three
  different "heads" instead of one.
- You're studying how much models agree with each other on open
  tasks (often: not much).

## How it works (one cook end-to-end)

```
                     ┌─────────────────────────────┐
                     │      cooks/260516-task/     │
                     │  BRIEF.md  JUDGE_BRIEF.md   │
                     │  brief.yaml      raw/       │
                     └──────────────┬──────────────┘
                                    │ multicooker cook
        ┌───────────────────────────┼───────────────────────────┐
        ▼                           ▼                           ▼
 ┌─────────────┐             ┌─────────────┐             ┌─────────────┐
 │  claude     │             │  codex      │             │  agy        │
 │  container  │   (parallel)│  container  │  (parallel) │  container  │
 │  net-A      │             │  net-B      │             │  net-C      │
 │  /work/...  │             │  /work/...  │             │  /work/...  │
 └──────┬──────┘             └──────┬──────┘             └──────┬──────┘
        │ out/                      │ out/                      │ out/
        └───────────────────────────┼───────────────────────────┘
                                    ▼
                       ┌─────────────────────────┐
                       │   anonymize → A/B/C     │
                       │   mapping stays on host │
                       └──────────────┬──────────┘
                                      │ multicooker judge
                ┌─────────────────────┼─────────────────────┐
                ▼                                           ▼
       ┌─────────────────┐                         ┌─────────────────┐
       │  judge-1        │                         │  judge-2        │
       │  (claude/codex/ │  scores everyone except │  (different     │
       │   agy)          │  its own flavor         │   flavor)       │
       └────────┬────────┘                         └────────┬────────┘
                │ scores.json + review.md                   │
                └─────────────────────┬─────────────────────┘
                                      ▼ multicooker report
                            ┌──────────────────┐
                            │ leaderboard.md   │
                            └──────────────────┘
```

The key properties:

- **Isolation.** Each participant runs in its own container on
  its own bridge network — can't see the other participants, the
  judge brief, or the `A↔flavor` mapping.
- **Parallelism.** All participants start at the same time. One
  being rate-limited doesn't block the others.
- **Anonymization.** Judges only see `A` / `B` / `C` with no
  model names. The mapping lives only on the host.
- **Anti-self-judge.** A judge never scores submissions from its
  own flavor — claude doesn't judge claude's output.
- **No API keys.** Subscription credentials (`Claude Pro` /
  `ChatGPT Plus` / `Gemini Advanced`) are passed into containers
  via bind-mount or named volume, read-only. See
  [`docs/auth.md`](docs/auth.md).

## Install

```bash
git clone https://github.com/faeton/multicooker
cd multicooker
pip install -e .
```

Requirements:

- macOS or Linux host with a running docker daemon. On macOS,
  **[OrbStack](https://orbstack.dev/)** is the recommended runtime
  — noticeably faster startup, lower idle CPU, and friendlier
  resource handling than Docker Desktop. Docker Desktop and colima
  also work.
- Python 3.10+.
- At least one of these CLIs installed and logged in: `claude`
  (`claude /login`), `codex` (`codex` to log in), `agy`
  (reuses your `~/.gemini/oauth_creds.json` OAuth), `grok`
  (`grok login`). Only the flavors you actually want to run.

Want to try the pipeline without subscription creds? There's a
`dummy` flavor — see [`examples/hello-task`](examples/hello-task/).

## Quick start: let an agent scaffold the cook (10 seconds)

The fastest way to use multicooker is to fire up an LLM agent
**inside the repo** and let it scaffold and run the cook for you.
The repo ships with a `CLAUDE.md` (and an `AGENTS.md` symlink for
codex / agy) that already explains the project, the shape of a
cook, and the rule that the rubric stays in sync between
`brief.yaml` and `JUDGE_BRIEF.md`. Any agent reading it can do the
boring part for you.

```bash
git clone https://github.com/faeton/multicooker && cd multicooker
pip install -e .

claude        # or: codex, or: agy — they all read AGENTS.md
```

Then describe what you want in plain language:

> *"Set up a cook called `landing-redesign`. Compare
> claude / codex / agy on a single-file HTML hero for [product].
> Judge on visual-hierarchy, typography, color-discipline,
> content-fit, polish. References are at `~/work/brand/notes.md`
> and `~/work/brand/voice.md`. Then run cook + judge + report."*

The agent reads `CLAUDE.md` and `examples/design-landing/` as
templates, drafts your `BRIEF.md` / `JUDGE_BRIEF.md` / `brief.yaml`,
copies the refs into `raw/`, kicks off `multicooker cook`, waits
for it to finish, then runs `judge` and `report`. You read the
leaderboard.

Iterating is the same conversation:

> *"Feedback for everyone: too much whitespace, push for denser
> layout. Specifically for `claude`: keep the color palette but
> tighten the type scale. Refine."*

Or — start a new cook reusing the same reference material (different
task, same brand assets):

> *"Same refs as the previous cook. New brief: a 3-frame onboarding
> sequence instead of a single landing. Judge the same dimensions
> plus story-clarity. Run it."*

This is the canonical workflow. The manual flow below is useful
for understanding the moving parts, but it's not how you'd
typically use the tool day-to-day.

## Manual flow (5 minutes, full control)

```bash
# 1. Preflight — docker, compose, creds for each flavor
multicooker doctor

# 2. Scaffold (name is auto-prefixed with today's date → 260509-my-task)
multicooker new my-task

# 3. Describe the task
cd cooks/260509-my-task
$EDITOR BRIEF.md          # what participants must do
$EDITOR JUDGE_BRIEF.md    # how judges will score
$EDITOR brief.yaml        # participants, judges, timeout, rubric
cp ~/some-reference.* raw/   # reference materials (mounted RO)

# 4. Cook — all participants in parallel, each in its own container
multicooker cook 260509-my-task

# 5. Judge — blind: judges only see A/B/C labels
multicooker judge 260509-my-task

# 6. Summary → leaderboard.md
multicooker report 260509-my-task
cat cooks/260509-my-task/leaderboard.md
```

## Examples

The repo includes two ready-to-run examples plus reusable cook shapes
for common task types:

- **[`examples/hello-task`](examples/hello-task/)** — sanitized
  smoke test on the `dummy` flavor, no LLM creds required. ~10
  seconds from start to leaderboard. Run it once to see the shape
  of a cook on the simplest possible task.

- **[`examples/design-landing`](examples/design-landing/)** — a
  real design task: each model designs its own landing page for
  `multicooker`. Three HTML files you then compare side-by-side in
  a browser. More on this below.

- **[`examples/technical-proposal`](examples/technical-proposal/)**
  — abstract RFC / architecture proposal. Use when the desired output is
  a clear build recommendation with alternatives, staged execution, and
  risk honesty.

- **[`examples/code-review-audit`](examples/code-review-audit/)**
  — source-reading review, known-issue root cause, and downstream refine
  guidance. Use before a risky patch or rewrite cook.

- **[`examples/implementation-spike`](examples/implementation-spike/)**
  — narrow working prototype with `README.md`, `STATUS.md`, source, and
  runnable evidence. Use after the target has been scoped.

- **[`examples/multi-concept-ui`](examples/multi-concept-ui/)**
  — three divergent self-contained UI concepts for one workflow. Use
  when you want interaction-model exploration, not one polished landing
  page.

## Use case: design and creative tasks

The most illustrative use case is tasks where there's no right
answer but there are quality criteria. Design, copy, naming,
architectural essays. Here models diverge not because one is buggy
but because they hold different "aesthetic beliefs", and comparison
becomes substantive.

`examples/design-landing` is a working template for this kind of
cook. Brief: *"design a landing page for multicooker, single-file
HTML, no build step"*. When you open the three `index.html` files
side by side, you typically see:

- **Palette.** One model commits to strict monochrome; another
  scatters six accent colors and doesn't quite know what to do
  with them; another defaults to dark mode.
- **Typography.** Someone reaches for the system stack; someone
  pulls Inter from Google Fonts; someone leaves the default
  `serif` — and the hero blocks read completely differently as a
  result.
- **Density.** One packs features into a three-column grid with
  small text; another goes for one big half-screen block.
- **Content fit.** Someone quotes `raw/product.md` verbatim;
  someone reimagines the product according to their own theories
  of what a "proper landing" should be (the `content-fit`
  dimension in the rubric exists to catch this).
- **Polish.** Hover states, spacing rhythm, code-block styling,
  footer treatment — small decisions that separate "draft" from
  "shipped".

The rubric in [`examples/design-landing/JUDGE_BRIEF.md`](examples/design-landing/JUDGE_BRIEF.md)
scores on `visual-hierarchy / typography / color-discipline /
content-fit / polish`. Two judges of different flavors score
blindly — and they often disagree with each other. That's a useful
signal: on design tasks, judge disagreement means there's no
"winner on points", just three different directions, and you pick
with your eyes.

```bash
# Run the design example (requires claude/codex/agy logins; grok optional)
multicooker new landing --participants claude,codex,agy,grok
TASK=$(basename "$(ls -d cooks/*-landing | tail -1)")
cp examples/design-landing/{BRIEF.md,JUDGE_BRIEF.md,brief.yaml} cooks/$TASK/
cp examples/design-landing/raw/* cooks/$TASK/raw/

multicooker cook   $TASK
multicooker judge  $TASK
multicooker report $TASK

# Open all three variants side by side, plus the leaderboard
open cooks/$TASK/out/*/index.html
cat  cooks/$TASK/leaderboard.md
```

This template adapts to any design task — SVG logo, README header,
email template, dashboard mockup. You only need to rewrite
`BRIEF.md` for your output and tweak the rubric dimensions
(`brand-fit`, `accessibility`, `density`, `motion-restraint` —
anything, as long as the names match between `brief.yaml` and
`JUDGE_BRIEF.md`). See
[`examples/design-landing/README.md`](examples/design-landing/README.md)
for the full adaptation guide.

## Iterating on a result

```bash
$EDITOR cooks/260509-my-task/FEEDBACK.md          # general feedback
$EDITOR cooks/260509-my-task/FEEDBACK_claude.md   # per-participant (optional)

multicooker refine 260509-my-task    # round N+1 on top of previous out/
multicooker judge  260509-my-task
multicooker report 260509-my-task
```

Previous rounds are preserved in `rounds/<N>/` — nothing is lost.
`multicooker diff <task>` shows what moved at file level between
two rounds — useful for spotting which model actually took the
feedback to heart vs which one just rephrased the previous answer.

## Multiple participants of the same flavor / different models

```bash
multicooker new comparison \
  --participants claude-a=claude,claude-b=claude,codex,agy
```

Per-participant model selection lives in `brief.yaml`:

```yaml
participants:
  - { name: claude-sonnet, flavor: claude, model: claude-sonnet-4-6 }
  - { name: claude-opus,   flavor: claude, model: claude-opus-4-7 }
  - { name: codex }
```

Useful for, e.g., pitting `sonnet` against `opus` on the same task
— two horses of the same flavor under different names, with
different models.

## Isolation and security (short version)

- One docker compose project per cook (`mc-<task>`).
- Each participant is in its own container on its own bridge
  network (`net-participant-<name>`); they don't see each other
  via DNS/IP.
- Subscription creds are snapshotted into `cooks/<task>/.auth/<flavor>/`
  (mode `0600`, `.gitignore`'d) and bind-mounted RO only into the
  corresponding container.
- After the cook, sealed `out/` is anonymized into `A/B/C/…`
  before judging. The `A↔flavor` mapping lives on the host only,
  never goes into judge containers.
- Egress to the internet is open. Sandbox = container, not network.
  Threat model: [`docs/security.md`](docs/security.md).

The long version: [`HOWTO.md`](HOWTO.md). Internals:
[`docs/orchestration.md`](docs/orchestration.md),
[`docs/auth.md`](docs/auth.md),
[`docs/lifecycle.md`](docs/lifecycle.md). Driving multicooker from an external
control plane: [`docs/control-plane-integration.md`](docs/control-plane-integration.md).

## Commands

| Command | What it does |
|---|---|
| `multicooker new <task> [--participants ...]` | Create a cook from templates. |
| `multicooker doctor [<task>]` | Preflight: docker, compose, creds, Dockerfiles, base images. |
| `multicooker build-base [<flavor>...]` | Build the shared base image (auto-built before the first cook). |
| `multicooker cook <task>` | Launch all participants in parallel. |
| `multicooker refine <task>` | Round N+1 with feedback on top of previous out. |
| `multicooker chef <task>` | Run one synthesis participant over sealed prior outputs. |
| `multicooker judge <task>` | Anonymized scoring by all judges. |
| `multicooker rejudge <task>` | Re-run judging (e.g. after editing `JUDGE_BRIEF.md`). |
| `multicooker lint <task>` | Check `brief.yaml` ↔ `JUDGE_BRIEF.md` consistency (rubric dimension coverage). |
| `multicooker report <task>` | Roll-up into `leaderboard.md` + `summary.json` + `artifacts.json`. |
| `multicooker artifacts <task> [--json]` | Build/show the visibility-tagged file manifest. |
| `multicooker archive <task> [--include-operator] [--format tar]` | Copy only publishable artifacts into a shareable dir/tarball. |
| `multicooker status <task> [--json]` | Current state from `status.json` (live; orchestrator-friendly). |
| `multicooker cancel <task>` | Stop a running cook, mark it cancelled, keep partial outputs. |
| `multicooker resume <task> [--force]` | Re-run only the retryable cells of the latest round. |
| `multicooker tail <task> [actor]` | Stream cell logs, prefixed by actor. |
| `multicooker diff <task>` | File-level diff between two refine rounds. |
| `multicooker add-participant <task> NAME[=FLAVOR]` | Add another participant to an existing cook. |
| `multicooker clean [<task>] [--all]` | `compose down -v --rmi local` + remove `.auth/` (keeps results). |
| `multicooker prune --older-than DAYS [--keep-results]` | Delete cooks older than N days (docker teardown + remove dir). Destructive. |

### Machine-readable contract (for orchestrators)

Every cook writes, alongside the human `leaderboard.md`:

- `status.json` — live point-in-time snapshot (cook + per-cell state),
  updated atomically through the run. Read it via `multicooker status`.
- `events.jsonl` — append-only event log (`cook.created`, `cell.started`,
  `cell.exited`, `seal.finished`, `judge.*`, `report.written`,
  `cook.cancel_requested`/`cook.cancelled`, …).
- `summary.json` — canonical final result after `report`: ranking, per-judge
  breakdown, run metrics for the latest round, excluded self-flavor pairs.
- `artifacts.json` — a manifest of every cook file tagged with a visibility
  class: `public` (leaderboard, summary, participant `out/`, judge reviews),
  `operator` (logs, traces, results), `secret` (`.auth/`), `host_only`
  (judge mappings, sealed inbox). Unknown files default to `operator`, never
  `public`. `multicooker archive` uses these classes to emit a shareable copy
  that never contains credentials or judge mappings.

An external control plane should drive cooks off these files rather than
parsing stdout or markdown. Full schemas, states, and the worker pattern:
[`docs/control-plane-integration.md`](docs/control-plane-integration.md).

### Python API

For embedding callers (e.g. a worker process), `multicooker.api` wraps the CLI:

```python
from multicooker import CookRequest, run_cook, run_judge, run_report, get_status

req = CookRequest(name="260527-example", root="/abs/path/cooks", namespace="zuzoo")
status = run_cook(req)      # runs `cook` in a subprocess, returns CookStatus
status = run_judge(req)
result = run_report(req)    # returns CookResult parsed from summary.json
print(result.ranking)
# poll a running cook from elsewhere without launching anything:
live = get_status("260527-example", "/abs/path/cooks")
```

Each `run_*` launches the CLI as a subprocess (no shared threads/locks with the
caller) and reads the result from the on-disk contract files. Prefer an absolute
`root`.

### Namespaces (multi-orchestrator)

Pass `--namespace <ns>` (or set `MULTICOOKER_NAMESPACE`) on `cook`/`judge`/
`refine`/`resume` and the compose project becomes `mc-<ns>-<cook>`, so two
orchestrators can run cooks with the same name without colliding on containers,
images, or networks. The resolved name is persisted in `compose.yaml`, so
`cancel` and `clean` find the right project without needing the flag again.

### Retention

`clean` only tears down docker artifacts and never deletes your results.
`multicooker prune --older-than DAYS` is the destructive one: it tears down each
stale cook's docker project and removes the directory (age from
`status.json.updated_at`). `--keep-results` preserves `summary.json` +
`leaderboard.md`; `--dry-run` lists without touching; `--prune-images` also
reclaims dangling images + build cache.

### Required outputs (optional)

Declare the deliverables a participant must produce, and a clean run that
doesn't write them is recorded as `artifact_missing` (not `ok`) — honest
status without aborting judging:

```yaml
outputs:
  required:
    - { path: RESULT.md, kind: markdown }   # path is relative to out/
```

A required path is satisfied only by a real, non-empty file. `multicooker lint`
(and `doctor`) check that every rubric dimension id in `brief.yaml` is mirrored
in `JUDGE_BRIEF.md`; `cook`/`refine` refuse to run if it isn't.

### Strict judge schema (optional)

By default `report` is tolerant — it repairs common judge-output variants
(unwraps `{"scores": …}`, lifts flat dimensions). For automation that needs to
trust the scores, opt into strict validation:

```yaml
judging:
  strict_schema: true
```

A judge whose `scores.json` doesn't match the canonical
`{"<label>": {"dimensions": {"<dim>": int}}}` shape is recorded as
`malformed_schema` (in `status.json`, `JUDGE_RESULT.json`, `summary.json`, and
the leaderboard's judge-run table) and its scores are **not** aggregated — no
silent repair. Re-run just the judging with `multicooker rejudge`.

## Status

`v0.2`. Tested on macOS with OrbStack and Docker Desktop. Linux
should work;
`claude` creds on darwin come from Keychain, on Linux from
`~/.claude/.credentials.json`.

Bugs → GitHub issues. Security: [`SECURITY.md`](SECURITY.md).

## License

[MIT](LICENSE).

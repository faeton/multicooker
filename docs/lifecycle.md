# Cook lifecycle: what gets created, when, and how to clean up

A reference for "what is this folder/file inside `cooks/<task>/`,
who wrote it, and when can I delete it."

## Created by `multicooker new <task>`

```
cooks/<task>/
├── BRIEF.md              # task description (you edit)
├── JUDGE_BRIEF.md        # rubric for judges (you edit)
├── brief.yaml            # participants/judges/timeouts/rubric (you edit)
├── raw/                  # reference materials (you fill, RO in container)
├── participants/         # per-flavor Dockerfile + entrypoint.sh
├── judge/                # judge Dockerfile + entrypoint.sh
└── work/<participant>/   # per-participant working tree (empty until cook)
```

`new` is idempotent on the cook name (refuses to overwrite). The
date prefix `YYMMDD-` is auto-applied unless you pass it yourself.

## Created by `multicooker cook <task>`

```
cooks/<task>/
├── .auth/                # creds snapshot (mode 0600), gitignored
├── .gitignore            # auto-extended with ".auth/"
├── compose.yaml          # rendered from brief.yaml
├── work/<p>/PROMPT.txt   # the prompt the agent sees
├── work/<p>/out/         # the agent writes here (RW mount)
├── work/<p>/usage/       # cook-local CLI usage ledgers for token parsing
├── logs/<p>/             # stdout.log / stderr.log per participant
├── judging/_inbox/<p>/   # sealed out/ + sanitized meta.json (judge input)
├── RUN_RESULT.json       # status + duration + token usage per p
├── status.json           # live cook + per-cell state (atomic; for `status`)
├── events.jsonl          # append-only event log (for orchestrators)
└── (transient docker images & volumes, removed by `clean`)
```

`.auth/` is rebuilt every cook so host-side token rotations are
picked up. `judging/_inbox/` is the boundary between the cook step
and the judge step — once written, the participants are done. It
holds **only** each participant's `out/` plus a sanitized `meta.json`
(`exit_class` + `round`) — never `PROMPT.txt`/`trace.json`/logs,
which would name the flavor to the blind judges.

`status.json`, `events.jsonl`, and (after `report`) `summary.json` +
`artifacts.json` are the machine-readable contract for an external control
plane — see `docs/control-plane-readiness.md`. `artifacts.json` tags every
file `public`/`operator`/`secret`/`host_only`; `multicooker archive` copies
only `public` (or `--include-operator`) into a shareable dir/tarball and
never touches `.auth/` or `judging/_mapping.json`. `cancel` adds a
`.mc-cancel` marker; `resume` archives prior attempts under
`attempts/round-<N>/<p>/`.

If `brief.yaml` declares `outputs.required`, each cell's `out/` is checked
after a clean exit: a participant that exited `ok` but didn't write a
declared deliverable (or wrote an empty/symlinked one) is recorded as
`artifact_missing` rather than `ok`. The check runs against the
participant's `work/<p>/out/` — keep required paths plain files
(`RESULT.md`), not basenames that `copytree_clean` strips on seal
(`node_modules`, `dist`, …). `artifact_missing` is **not** a retryable
state, so `resume` skips it unless `--force`.

## Created by `multicooker refine <task>`

```
cooks/<task>/
├── rounds/<N>/<p>/       # snapshot of round N's out/ (immutable)
├── rounds/<N>/_inbox/    # snapshot of round N's sealed inbox
├── REFINE_<N>.json       # round N start metadata
├── REFINE_<N>_RESULT.json# round N finish summary
├── FEEDBACK.md           # shared feedback (you write before refine)
└── FEEDBACK_<flavor>.md  # per-participant feedback (optional, you write)
```

`work/<p>/out/` is **not** wiped — the agent edits it in place.
Previous rounds live in `rounds/<N>/`.

## Created by `multicooker judge <task>`

```
cooks/<task>/
├── judging/_mapping.json          # A↔participant↔flavor (host only, NEVER in container)
├── judging/<judge>/submissions/   # anonymized A/B/C copies
├── judging/<judge>/outbox/scores.json  # judge's verdict
├── judging/<judge>/outbox/review.md    # judge's commentary
├── judging/_usage/<judge>/        # cook-local judge usage ledgers
├── JUDGE_RESULT.json              # status + duration + token usage per judge
└── (per-judge logs under logs/<judge>/)
```

Anonymization is one-shot — re-running `judge` shuffles the labels
again and overwrites `_mapping.json`.

## Created by `multicooker report <task>`

```
cooks/<task>/leaderboard.md   # human-readable report
cooks/<task>/summary.json     # canonical machine-readable result
```

`leaderboard.md` is a markdown summary aggregating all judges'
`scores.json` against the rubric weights from `brief.yaml`.
`summary.json` is the same data for machines: ranking, per-judge
breakdown, latest-round run metrics, and excluded self-flavor pairs.
Both are idempotent — safe to re-run.

## Cleanup

- `multicooker clean <task>` — `docker compose down -v --rmi local` for
  the cook's compose project, plus removes `.auth/`. Add
  `--keep-creds` to skip the auth wipe; `--dry-run` to preview.
- `multicooker clean --all` — same, for every `cooks/*/`.
- `rm -rf cooks/<task>/` — nuclear; safe because `cooks/` is in the
  repo `.gitignore`.

## What's safe to delete by hand

| Path | Safe to delete? | Why |
|---|---|---|
| `.auth/` | Yes | Re-snapshotted on next `cook`/`refine`/`judge`. |
| `compose.yaml` | Yes | Re-rendered on next run. |
| `logs/` | Yes | Just stdout/stderr from past runs. |
| `judging/` | Yes, but you lose past verdicts | Re-running `judge` rebuilds. |
| `RUN_RESULT.json` | Yes | Just metadata, not load-bearing. |
| `work/<p>/out/` | **No** if you plan to `refine` | Refine reads previous out as the "in-progress draft." If gone, refine becomes a fresh cook. |
| `rounds/<N>/` | **No** | Immutable history. Delete only if you want to drop that round forever. |
| `raw/`, `BRIEF.md`, `brief.yaml`, `JUDGE_BRIEF.md` | **No** | These are your inputs. |

## What's checked in vs ignored

- `cooks/` — globally gitignored.
- `multicooker/templates/cook/` — checked in (the seed for new cooks).
- `examples/hello-task/` — checked in (sanitized example, dummy flavor).

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
├── judging/_inbox/<p>/   # sealed copy of out/ (input to judging)
├── RUN_RESULT.json       # status + duration + token usage per p
└── (transient docker images & volumes, removed by `clean`)
```

`.auth/` is rebuilt every cook so host-side token rotations are
picked up. `judging/_inbox/` is the boundary between the cook step
and the judge step — once written, the participants are done.

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
cooks/<task>/leaderboard.md
```

A markdown summary aggregating all judges' `scores.json` against
the rubric weights from `brief.yaml`. Idempotent — safe to re-run.

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

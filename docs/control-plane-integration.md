# Driving multicooker from a control plane (Zuzoo)

This is the integration guide for an external control plane — Zuzoo or any other
orchestrator — that wants to run cooks unattended and read structured results.
It documents the **stable contract**: what files multicooker writes, what the
commands do, what states mean, and what is safe to publish.

The design boundary (see `control-plane-readiness.md`): multicooker stays a CLI
+ cook-directory docker engine. The control plane owns chat UI, approvals,
durable user-facing state, quota policy, and scheduling. Between them is a small
file contract — task files in; structured status, events, results, artifacts
out. **Drive cooks off these files, never by scraping stdout or parsing
markdown.**

## The worker pattern

```
1. materialize a cook directory  (multicooker new <name>, then fill brief.yaml,
                                   BRIEF.md, JUDGE_BRIEF.md, raw/)
2. multicooker lint <name>        # fail fast on rubric drift (optional, cheap)
3. multicooker cook <name>        # participants run in parallel containers
4. multicooker judge <name>       # blind, anonymized scoring
5. multicooker report <name>      # leaderboard.md + summary.json + artifacts.json
6. read summary.json / artifacts.json; publish only `public` artifacts
```

While a cook runs, poll `status.json` / follow `events.jsonl`; `cancel` to stop;
`resume` to retry only the failed cells. Running phases, cancelling, and reading
`status.json`/`summary.json`/`artifacts.json` are available through the
[Python API](#python-api); to follow `events.jsonl`, read the file directly
(`multicooker tail` streams the cell **logs**, not the event stream).

## Contract files

Every cook directory (`cooks/<name>/`) carries these machine-readable files.
`status.json`, `summary.json`, and `artifacts.json` are replaced atomically
(temp file + `os.replace`); `status.json` read-modify-writes and `events.jsonl`
appends happen under a cross-process `flock`, and each event is written as a
single append. A reader of `status.json` never sees a half-written snapshot.

### `status.json` — live point-in-time snapshot

Replaced atomically on every state change; safe to poll.

```json
{
  "schema_version": 1,
  "cook": "260527-example",
  "phase": "cook",
  "state": "cooking",
  "round": 1,
  "updated_at": "2026-05-27T18:20:00+00:00",
  "cells": {
    "codex": {
      "role": "participant",
      "flavor": "codex",
      "state": "running",
      "started_at": "2026-05-27T18:19:10+00:00",
      "finished_at": null,
      "exit_class": null,
      "duration_s": null
    }
  }
}
```

A cell may also carry `"missing": [...]` (declared outputs that were absent — see
`artifact_missing` below).

**Cook states** (`state`):

| state | meaning |
|---|---|
| `created` | status initialized, nothing launched yet |
| `preflighting` | snapshotting creds |
| `building` | building docker images |
| `cooking` | participants running |
| `sealed` | participants done, outputs sealed for judging (NOT terminal) |
| `judging` | judges running |
| `reported` | leaderboard + summary written (terminal) |
| `cancelled` | stopped by `cancel` (terminal) |
| `failed` | a phase failed before sealing (terminal) |

Treat `reported`, `cancelled`, `failed` as terminal. `sealed` is mid-pipeline —
it's the handoff awaiting `judge`.

**Cell states** (`cells.<name>.state`):

| state | retryable by `resume`? | meaning |
|---|---|---|
| `pending` / `starting` / `running` | — | not finished |
| `ok` | no | clean exit, deliverables present |
| `rate_limited` | **yes** | hit the flavor's usage limit |
| `timed_out` | **yes** | exceeded `timeout_s` |
| `start_failed` | **yes** | container failed to launch |
| `non_zero_exit` | **yes** | CLI exited nonzero |
| `oom_killed` | no | killed by the OOM killer (raise mem, don't blind-retry) |
| `cancelled` | no | stopped mid-run by `cancel` |
| `artifact_missing` | no | exited cleanly but a required output is missing/empty |

For judges, `exit_class` additionally distinguishes `no_scores`,
`invalid_json`, and (in strict mode) `malformed_schema`; the cell `state` is
`non_zero_exit` in those cases. Re-run judging with `rejudge`.

### `events.jsonl` — append-only event log

One JSON object per line; follow it to track progress without polling.

```json
{"ts": "2026-05-27T18:20:00+00:00", "event": "cell.exited", "cook": "260527-example", "phase": "cook", "actor": "codex", "payload": {"exit_class": "ok", "duration_s": 326.7}}
```

Event names: `cook.created`, `phase.started`, `image.build.started`,
`image.build.finished`, `cell.started`, `cell.exited`, `cell.rate_limited`,
`seal.finished`, `judge.started`, `judge.finished`, `report.written`,
`cook.cancel_requested`, `cook.cancelled`, `cook.failed`. A `cell.exited` for an
artifact-missing cell carries `payload.missing_outputs`.

### `summary.json` — canonical final result

Written by `report`. This is what you build core logic on.

```json
{
  "schema_version": 1,
  "cook": "260527-example",
  "round": 1,
  "generated_at": "2026-05-27T18:40:00+00:00",
  "anti_self_judge_policy": "warn",
  "judges_used": ["judge-claude", "judge-codex"],
  "ranking": [
    {"rank": 1, "participant": "codex", "flavor": "codex", "mean_pct": 82.5,
     "num_judges": 2, "run_status": "ok", "duration_s": 326.7,
     "tokens": 154233, "cost_usd": null}
  ],
  "per_judge": {
    "judge-claude": {"codex": {"dimensions": {"correctness": 4}, "score_pct": 80.0, "excluded": false}}
  },
  "judge_run": [{"name": "judge-claude", "status": "ok", "duration_s": 41.2}],
  "excluded_pairs": [{"judge": "judge-claude", "participant": "claude", "flavor": "claude"}],
  "artifacts": {"leaderboard": "leaderboard.md", "manifest": "artifacts.json"}
}
```

If no judge produced usable scores, `report` returns a **nonzero exit**, writes
`summary.json` with `"status": "no_scores"`, an empty `ranking`, and `judge_run`
carrying each judge's failure status — so a reader always finds a valid file.
In that case it does **not** write `leaderboard.md` or `artifacts.json`, emit
`report.written`, or move the cook to `reported`. So don't wait for
`state == "reported"` to decide a cook is done: treat a nonzero `report` exit
**or** `summary.json.status == "no_scores"` as "judging produced nothing" and
fix/`rejudge` from there.

`round` reflects the latest round: after `refine`, the metrics come from
`REFINE_<N>_RESULT.json`, not the stale round-1 `RUN_RESULT.json`.

The `anti_self_judge_policy` field echoes the policy actually applied (see
below), and `excluded_pairs` lists the (judge, participant) pairs dropped under
the strict policy — empty under `warn`/`allow_self`.

### Judging policy — blind judging is opt-in

Whether a judge may score a submission of its **own flavor** is governed by
`judging.policy` in `brief.yaml`, with three values:

| policy | same-flavor scores | use for |
|---|---|---|
| `require_distinct_flavor` | dropped before aggregation, recorded in `excluded_pairs` | **unattended / control-plane runs** |
| `warn` (**default**) | kept; an advisory is printed | interactive, when you accept the bias |
| `allow_self` | kept silently | — |

The default is `warn`, so **absent an explicit policy the blind-judging
guarantee does not hold** — a same-flavor judge's scores still affect the
ranking. A control plane that wants the guarantee must set `judging.policy: require_distinct_flavor` in each cook's
`brief.yaml` before `cook`. (Sealing/anonymization — letters instead of flavor names — is
always on; this policy is only about whether self-flavor *scores* are counted.)

### `artifacts.json` — visibility manifest

Written by `report` (or on demand via `multicooker artifacts <name>`). Tags
every file so the control plane knows what is safe to publish.

```json
{
  "schema_version": 1,
  "cook": "260527-example",
  "generated_at": "2026-05-27T18:40:00+00:00",
  "artifacts": [
    {"path": "leaderboard.md", "kind": "markdown", "visibility": "public", "size": 1820, "sha256": "..."},
    {"path": ".auth/claude/creds.json", "kind": "json", "visibility": "secret", "size": 412, "sha256": "..."}
  ]
}
```

**Visibility classes:**

| class | publish? | examples |
|---|---|---|
| `public` | yes | `leaderboard.md`, `summary.json`, each participant's `work/<p>/out/`, sanitized judge `review.md` |
| `operator` | debugging only | logs, `trace.json`, `RUN*.json`, `status.json`, `events.jsonl`, `compose.yaml`, `raw/`, briefs |
| `secret` | never | `.auth/` (credentials) |
| `host_only` | never | `judging/_mapping.json`, the sealed `_inbox/`, judge work dirs |

Classification is **denylist-first** and an **unknown path defaults to
`operator`, never `public`** — a new file type can't accidentally become
publishable. Symlinks and special files (FIFO/socket) are flagged and never
hashed or archived.

## Publishing safely

Use `multicooker archive <name>` rather than hand-copying:

```bash
multicooker archive 260527-example                     # → cooks/<name>/archive/ (public only)
multicooker archive 260527-example --include-operator  # also logs/traces
multicooker archive 260527-example --format tar        # → <name>-archive.tar.gz
```

`archive` copies only `public` (or `public + operator`) files, **never** `secret`
/`host_only`. It skips symlinks and verifies every copied file's real path stays
inside the cook directory — a participant cannot smuggle a host secret out via a
symlink in its `out/`. A filtered `artifacts.json` ships inside the archive.

**Blind-judging guarantee:** each participant's work is sealed to
`judging/_inbox/<p>/` as only its `out/` plus a sanitized `meta.json`
(`exit_class` + `round`) — no flavor/model/name. `judge` then anonymizes that
into `judging/_judge_input/submissions/<letter>/`, which is the actual
judge-visible input (copied into each judge's container). The
`<letter>→participant` mapping lives only in `judging/_mapping.json` (host-only)
and never enters a judge container; flavor isn't in the mapping at all.

## Namespaces (running many orchestrators)

Pass `--namespace <ns>` (or set `MULTICOOKER_NAMESPACE`) on `cook`/`judge`/
`refine`/`resume`. The compose project becomes `mc-<ns>-<cook>`, so two
orchestrators can run cooks with the same name without colliding on containers,
images, or networks. The resolved name is persisted in `compose.yaml`.

Stickiness rule: an explicit namespace **always wins** — and "explicit" means
*either* the `--namespace` flag *or* a set `MULTICOOKER_NAMESPACE` env var. Only
when **neither** is provided does a later `judge`/`refine`/`resume` reuse the
cook's persisted project from `compose.yaml`. So keep `MULTICOOKER_NAMESPACE`
consistent across a cook's phases: if it's set to a different value (or set on
some phases but not others) the project is recomputed and the original
containers/images are orphaned. `cancel`/`clean` always read the persisted name
back, so they target the right project regardless.

## Retention

- `multicooker clean <name>` — tears down docker artifacts (`compose down -v
  --rmi local`) + removes `.auth/`. **Never deletes your results.**
- `multicooker prune --older-than DAYS` — destructive: docker teardown **and**
  removal of every cook whose `status.json.updated_at` is older than `DAYS`
  (falling back to the newest result-file mtime, then the directory mtime, when
  `status.json` is absent). `--keep-results` preserves `summary.json` +
  `leaderboard.md`; `--dry-run` lists; `--prune-images` also reclaims dangling
  images + build cache.

A long-lived installation can run `prune --older-than 30 --keep-results` on a
schedule to reclaim disk while keeping verdicts.

## Python API

For an embedding worker, `multicooker.api` wraps the CLI (re-exported from the
package root). Each `run_*` launches the CLI as a **subprocess** (no shared
threads or locks with your process) and reads the contract files back.

```python
from multicooker import CookRequest, run_cook, run_judge, run_report, get_status, cancel

req = CookRequest(name="260527-example", root="/abs/cooks", namespace="zuzoo")

st = run_cook(req)        # CookStatus; st.state, st.cells, st.exit_code
if st.exit_code == 0:
    run_judge(req)
    result = run_report(req)          # CookResult parsed from summary.json
    for row in result.ranking:
        print(row["rank"], row["participant"], row["mean_pct"])

# from a different process, poll without launching anything:
live = get_status("260527-example", "/abs/cooks")   # None until the cook starts
if live and not live.is_terminal:
    ...  # still running

cancel("260527-example", "/abs/cooks")               # stop, keep partial outputs
```

Notes:
- `run_*` always return an object carrying the subprocess `exit_code` (a stub
  with `state=None` / `status="missing"` if the run died before writing its
  file), so you never get a bare `None` that hides the exit code.
- Read-only `get_status`/`get_result`/`get_artifacts` return `None` when the file
  doesn't exist yet (e.g. polling a not-yet-started cook).
- Prefer an absolute `root` (str or `Path` both work).

## Definition of done

multicooker is ready for Zuzoo-style orchestration: an external process can
create a cook dir, run `cook`/`judge`/`report`, read live progress from
`status.json` + `events.jsonl`, `cancel`, `resume` retryable cells, read the
final result from `summary.json`, and publish only safe files per
`artifacts.json` — without parsing markdown, stdout, or raw logs.
